"""The Ingeteam Modbus Integration."""
import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MODBUS_ADDRESS,
    CONF_MODBUS_ADDRESS,
    CONF_READ_METER,
    CONF_READ_BATTERY,
    DEFAULT_READ_METER,
    DEFAULT_READ_BATTERY,
    BOOLEAN_STATUS,
    INVERTER_STATUS,
    BATTERY_STATUS,
    BATTERY_BMS_ALARMS,
    BATTERY_LIMITATION_REASONS,
    AP_REDUCTION_REASONS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Number of input registers read in a single request (30001 .. 30081).
REGISTER_COUNT = 81


def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return an entry option, falling back to the original entry data."""
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Set up the Ingeteam modbus component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an Ingeteam modbus hub from a config entry."""
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    port = int(entry.data[CONF_PORT])
    address = _option(entry, CONF_MODBUS_ADDRESS, DEFAULT_MODBUS_ADDRESS)
    scan_interval = _option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    read_meter = _option(entry, CONF_READ_METER, DEFAULT_READ_METER)
    read_battery = _option(entry, CONF_READ_BATTERY, DEFAULT_READ_BATTERY)

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)

    hub = IngeteamModbusHub(
        hass,
        name,
        host,
        port,
        address,
        scan_interval,
        read_meter,
        read_battery,
    )

    if not await hub.async_initialize():
        # Do not leak the socket: HA will retry the setup with a new hub.
        await hass.async_add_executor_job(hub.close)
        raise ConfigEntryNotReady(f"Could not read from {host}:{port}")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][name] = {"hub": hub, "entry_id": entry.entry_id}
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Ingeteam modbus entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    name = entry.data[CONF_NAME]
    stored = hass.data.get(DOMAIN, {}).get(name)
    # Another entry may have taken over this name already.
    if stored is not None and stored.get("entry_id") == entry.entry_id:
        await stored["hub"].async_shutdown()
        hass.data[DOMAIN].pop(name)
    return True


class IngeteamModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(self, hass, name, host, port, address, scan_interval, read_meter=True, read_battery=False):
        """Initialize the Modbus hub."""
        self._hass = hass
        self._client = ModbusTcpClient(host=host, port=port, timeout=max(3, (scan_interval - 1)))
        self._lock = threading.Lock()
        self._name = name
        self._address = address
        self._host = host
        self._port = port
        self.read_meter = read_meter
        self.read_battery = read_battery
        self.online = False
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensors = []
        self.data: Dict[str, Any] = {}

    async def async_initialize(self) -> bool:
        """Connect and perform the first read, so the entities start populated."""
        if not await self._hass.async_add_executor_job(self.connect):
            return False
        self.online = await self._hass.async_add_executor_job(self._update_modbus_data)
        return self.online

    async def async_add_ingeteam_sensor(self, update_callback) -> None:
        """Listen for data updates."""
        if not self._sensors:
            await self._hass.async_add_executor_job(self._ensure_connected)
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_refresh_modbus_data, self._scan_interval
            )
        self._sensors.append(update_callback)

    async def async_remove_ingeteam_sensor(self, update_callback) -> None:
        """Remove data update."""
        if update_callback in self._sensors:
            self._sensors.remove(update_callback)
        if not self._sensors:
            await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Stop polling and close the connection."""
        if self._unsub_interval_method:
            self._unsub_interval_method()
            self._unsub_interval_method = None
        await self._hass.async_add_executor_job(self.close)

    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> None:
        """Time to update."""
        if not self._sensors:
            return
        was_online = self.online
        update_result = await self._hass.async_add_executor_job(self._update_modbus_data)
        self.online = update_result
        # Notify on success and on the transition to unavailable, so the
        # entities never keep showing a stale value as if it were live.
        if update_result or was_online:
            for update_callback in list(self._sensors):
                update_callback()

    def _update_modbus_data(self) -> bool:
        """Synchronously fetch data from the modbus device. To be run in an executor."""
        if not self._ensure_connected():
            return False
        try:
            return self.read_modbus_data()
        except ModbusException as e:
            _LOGGER.warning("Modbus exception occurred while reading data: %s", e)
            return False
        except Exception:
            _LOGGER.exception("Unexpected error while reading modbus data")
            return False

    @property
    def name(self):
        """Return the name of this hub."""
        return self._name

    def close(self):
        """Disconnect client. Blocking: run it in an executor."""
        with self._lock:
            self._client.close()

    def _ensure_connected(self) -> bool:
        """Check connection and reconnect if needed. Blocking."""
        with self._lock:
            if not self._client.is_socket_open():
                _LOGGER.info("Modbus client is not connected, trying to reconnect")
                return self._client.connect()
            return True

    def connect(self) -> bool:
        """Connect client. Blocking: run it in an executor."""
        with self._lock:
            result = self._client.connect()
            if result:
                _LOGGER.info("Successfully connected to %s:%s", self._host, self._port)
            else:
                _LOGGER.warning("Could not connect to %s:%s", self._host, self._port)
            return result

    def read_input_registers(self, unit, address, count):
        """Read input registers."""
        with self._lock:
            return self._client.read_input_registers(address=address, count=count, device_id=unit)

    # -------------------------
    # Utilidades de decodificación
    # -------------------------
    @staticmethod
    def _decode_signed(value: int) -> int:
        """Decode a 16-bit signed integer (two's complement)."""
        if value & 0x8000:
            return value - 0x10000
        return value

    @staticmethod
    def _u32_from_words_le(registers, start_index: int) -> int:
        """
        Combina dos registros de 16 bits en un uint32.
        Orden de palabras 'little' (wordorder LITTLE): low word primero.
        Cada palabra mantiene su endianness de bytes (como en BIG del decoder original),
        por lo que basta con desplazar 16 bits la palabra alta.
        """
        low = registers[start_index]
        high = registers[start_index + 1]
        return (high << 16) | low

    @staticmethod
    def _decode_bms_alarms(mask: int) -> str:
        """Decode the BMS alarm bit mask into a readable list."""
        active = [name for bit, name in BATTERY_BMS_ALARMS.items() if mask & (1 << bit)]
        if not active:
            return "No alarm"
        return ", ".join(active)

    # -------------------------
    # Lectura y parseo principal
    # -------------------------
    def read_modbus_data(self) -> bool:
        """Read and decode all registers in a single, optimized function."""
        all_regs_response = self.read_input_registers(
            unit=self._address, address=0, count=REGISTER_COUNT
        )
        if all_regs_response.isError():
            _LOGGER.error("Error reading modbus registers: %s", all_regs_response)
            return False

        registers = all_regs_response.registers
        if len(registers) < REGISTER_COUNT:
            _LOGGER.warning(
                "Incomplete Modbus response, expected %s registers but got %s",
                REGISTER_COUNT,
                len(registers),
            )
            return False

        # Decoded into a local dict and published in one assignment, so the
        # event loop never reads a half-updated snapshot.
        data: Dict[str, Any] = {}

        # --- Inverter Status & Lifetime ---
        data["total_operation_time"] = self._u32_from_words_le(registers, 6)  # Reg 30007-8
        data["stop_code"] = registers[9]  # Reg 30010
        data["alarm_code"] = self._u32_from_words_le(registers, 10)  # Reg 30011-12

        status_code = registers[15]  # Reg 30016
        data["status"] = INVERTER_STATUS.get(status_code, f"Unknown ({status_code})")
        data["waiting_time"] = registers[16]  # Reg 30017

        # --- Battery Data ---
        data["battery_voltage"] = registers[17] / 10.0
        data["battery_current"] = self._decode_signed(registers[18]) / 100.0
        battery_power = self._decode_signed(registers[19])
        data["battery_discharging_power"] = max(0, battery_power)
        data["battery_charging_power"] = max(0, -battery_power)
        data["battery_state_of_charge"] = registers[20]
        data["battery_state_of_health"] = registers[21]
        data["battery_charging_voltage"] = registers[22] / 10.0
        data["battery_discharging_voltage"] = registers[23] / 10.0
        data["battery_charging_current_max"] = registers[24] / 100.0
        data["battery_discharging_current_max"] = registers[25] / 100.0
        batt_status_code = registers[26]
        data["battery_status"] = BATTERY_STATUS.get(batt_status_code, f"Unknown ({batt_status_code})")
        data["battery_temp"] = self._decode_signed(registers[27]) / 10.0
        data["battery_bms_alarm"] = registers[28]
        data["battery_bms_alarms"] = self._decode_bms_alarms(registers[28])
        batt_limit_code = registers[29]
        data["battery_discharge_limitation_reason"] = BATTERY_LIMITATION_REASONS.get(
            batt_limit_code, f"Unknown ({batt_limit_code})"
        )
        data["battery_voltage_internal"] = registers[30] / 10.0
        data["battery_bms_flags"] = registers[68]  # Reg 30069
        data["battery_bms_warnings"] = registers[73]  # Reg 30074
        data["battery_bms_errors"] = registers[74]  # Reg 30075
        data["battery_bms_faults"] = registers[75]  # Reg 30076
        batt_charge_limit_code = registers[77]  # Reg 30078
        data["battery_charge_limitation_reason"] = BATTERY_LIMITATION_REASONS.get(
            batt_charge_limit_code, f"Unknown ({batt_charge_limit_code})"
        )

        # --- PV Data ---
        data["pv1_voltage"] = registers[31]
        data["pv1_current"] = registers[32] / 100.0
        data["pv1_power"] = registers[33]
        data["pv2_voltage"] = registers[34]
        data["pv2_current"] = registers[35] / 100.0
        data["pv2_power"] = registers[36]
        data["external_pv_power"] = registers[79]
        data["ev_power"] = self._decode_signed(registers[80])
        data["pv_internal_total_power"] = data["pv1_power"] + data["pv2_power"]
        data["pv_total_power"] = data["pv_internal_total_power"] + data["external_pv_power"]

        # --- Inverter & Loads Data ---
        data["active_power"] = self._decode_signed(registers[37])
        data["reactive_power"] = self._decode_signed(registers[38])
        data["power_factor"] = self._decode_signed(registers[39]) / 1000.0
        data["ap_reduction_ratio"] = registers[40] / 10.0
        ap_reason_code = registers[41]
        data["ap_reduction_reason"] = AP_REDUCTION_REASONS.get(ap_reason_code, f"Unknown ({ap_reason_code})")
        data["reactive_setpoint_type"] = registers[42]
        data["cl_voltage"] = registers[43]
        data["cl_current"] = registers[44] / 100.0
        data["cl_freq"] = registers[45] / 100.0
        data["cl_active_power"] = self._decode_signed(registers[46])
        data["cl_reactive_power"] = self._decode_signed(registers[47])
        data["total_loads_power"] = registers[78]
        data["dc_bus_voltage"] = registers[54]
        data["positive_isolation_resistance"] = registers[59]  # Reg 30060
        data["negative_isolation_resistance"] = registers[60]  # Reg 30061
        data["temp_mod_1"] = self._decode_signed(registers[55]) / 10.0
        data["temp_mod_2"] = self._decode_signed(registers[56]) / 10.0
        data["temp_pcb"] = self._decode_signed(registers[57]) / 10.0
        data["rms_diff_current"] = registers[61] / 10.0
        data["do_1_status"] = BOOLEAN_STATUS.get(registers[62], "Unknown")
        data["do_2_status"] = BOOLEAN_STATUS.get(registers[63], "Unknown")
        data["di_drm_status"] = BOOLEAN_STATUS.get(registers[64], "Unknown")
        data["di_2_status"] = BOOLEAN_STATUS.get(registers[65], "Unknown")
        data["di_3_status"] = BOOLEAN_STATUS.get(registers[66], "Unknown")

        # --- Meter Data ---
        data["im_voltage"] = registers[48]
        data["im_current"] = registers[49] / 100.0
        data["im_freq"] = registers[50] / 100.0
        data["im_active_power"] = self._decode_signed(registers[51])
        data["im_reactive_power"] = self._decode_signed(registers[52])
        data["im_power_factor"] = self._decode_signed(registers[53]) / 1000.0
        data["em_voltage"] = registers[69]
        data["em_freq"] = registers[70] / 10.0
        grid_power = self._decode_signed(registers[71])
        data["em_active_power"] = max(0, grid_power)
        data["em_active_power_returned"] = max(0, -grid_power)
        data["em_reactive_power"] = self._decode_signed(registers[72])

        self.data = data
        return True
