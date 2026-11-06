"""The Ingeteam Modbus Integration."""
import logging
import threading
from datetime import timedelta
from typing import Any, Dict, List

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_PORT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    DOMAIN,
    DEFAULT_MODBUS_ADDRESS,
    CONF_MODBUS_ADDRESS,
    MODBUS_BLOCKS,
    MODBUS_TIMEOUT,
    ModbusBlock,
    BOOLEAN_STATUS,
    INVERTER_STATUS,
    BATTERY_STATUS,
    BATTERY_BMS_ALARMS,
    BATTERY_LIMITATION_REASONS,
    AP_REDUCTION_REASONS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# How long a block waits for the socket to be free before giving up on this
# tick. Three blocks share the 5 s cadence one second apart, so a read that
# outlives its slot must be skipped rather than queued.
LOCK_TIMEOUT = 1


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

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)

    hub = IngeteamModbusHub(
        hass,
        name,
        host,
        port,
        address,
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

    def __init__(self, hass, name, host, port, address):
        """Initialize the Modbus hub."""
        self._hass = hass
        self._client = ModbusTcpClient(host=host, port=port, timeout=MODBUS_TIMEOUT)
        self._lock = threading.Lock()
        self._name = name
        self._address = address
        self._host = host
        self._port = port
        self.online = False
        self._unsub_callbacks: List[Any] = []
        self._sensors = []
        self.data: Dict[str, Any] = {}

    async def async_initialize(self) -> bool:
        """Connect and read every block once, so the entities start populated.

        Without this, the entities fed by the slow blocks would sit at
        "unavailable" for up to 90 seconds after a reload.
        """
        if not await self._hass.async_add_executor_job(self.connect):
            return False

        online = False
        for block in MODBUS_BLOCKS:
            result = await self._hass.async_add_executor_job(self._update_block, block)
            if block.primary:
                online = result

        # Only the primary block decides whether the hub is usable: the others
        # get retried on their own first tick.
        self.online = online
        return self.online

    async def async_add_ingeteam_sensor(self, update_callback) -> None:
        """Listen for data updates."""
        if not self._sensors:
            await self._hass.async_add_executor_job(self._ensure_connected)
            self._schedule_blocks()
        self._sensors.append(update_callback)

    async def async_remove_ingeteam_sensor(self, update_callback) -> None:
        """Remove data update."""
        if update_callback in self._sensors:
            self._sensors.remove(update_callback)
        if not self._sensors:
            await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Stop polling and close the connection."""
        for unsub in self._unsub_callbacks:
            unsub()
        self._unsub_callbacks.clear()
        await self._hass.async_add_executor_job(self.close)

    # -------------------------
    # Scheduling
    # -------------------------
    @callback
    def _schedule_blocks(self) -> None:
        """Start one timer per register block."""
        for block in MODBUS_BLOCKS:
            self._schedule_block(block)

    @callback
    def _schedule_block(self, block: ModbusBlock) -> None:
        """Delay a block by its offset, then poll it at its own interval.

        Every interval is a multiple of the 5 s base window and every offset is
        a different whole second inside it, so the phase difference between
        blocks is preserved for as long as the hub lives and two reads never
        start at the same instant.
        """
        interval = timedelta(seconds=block.interval)
        offset_unsub = None

        async def _refresh(_now=None) -> None:
            await self.async_refresh_block(block)

        @callback
        def _start(_now) -> None:
            # The one shot has fired: from here on only the recurring timer
            # needs cancelling.
            if offset_unsub in self._unsub_callbacks:
                self._unsub_callbacks.remove(offset_unsub)
            self._unsub_callbacks.append(
                async_track_time_interval(self._hass, _refresh, interval)
            )
            # Read now too, so the recurring timer keeps this block's phase.
            self._hass.async_create_task(_refresh())

        offset_unsub = async_call_later(self._hass, block.offset, _start)
        self._unsub_callbacks.append(offset_unsub)

    async def async_refresh_block(self, block: ModbusBlock) -> None:
        """Time to update one block."""
        if not self._sensors:
            return
        was_online = self.online
        result = await self._hass.async_add_executor_job(self._update_block, block)

        if block.primary:
            self.online = result

        # Notify on success and on the transition to unavailable, so the
        # entities never keep showing a stale value as if it were live. A
        # failure of a non primary block changes nothing: its old values stay.
        if result or (block.primary and was_online):
            for update_callback in list(self._sensors):
                update_callback()

    def _update_block(self, block: ModbusBlock) -> bool:
        """Fetch one block from the device. To be run in an executor."""
        if not self._ensure_connected():
            return False
        try:
            return self._read_block(block)
        except ModbusException as e:
            _LOGGER.warning(
                "Modbus exception occurred while reading block %s: %s", block.key, e
            )
            return False
        except Exception:
            _LOGGER.exception("Unexpected error while reading block %s", block.key)
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
    # Lectura por bloques
    # -------------------------
    def _read_block(self, block: ModbusBlock) -> bool:
        """Read one register block and merge its decoded values. Blocking."""
        # Skip this tick rather than queueing work in the executor behind a
        # read that is taking longer than its slot.
        if not self._lock.acquire(timeout=LOCK_TIMEOUT):
            _LOGGER.debug("Block %s skipped: another read is still in flight", block.key)
            return False
        try:
            response = self._client.read_input_registers(
                address=block.address, count=block.count, device_id=self._address
            )
        finally:
            self._lock.release()

        if response.isError():
            _LOGGER.error("Error reading modbus block %s: %s", block.key, response)
            return False

        registers = response.registers
        if len(registers) < block.count:
            _LOGGER.warning(
                "Incomplete Modbus response for block %s, expected %s registers but got %s",
                block.key,
                block.count,
                len(registers),
            )
            return False

        decoded = getattr(self, f"_decode_{block.key}")(registers)

        # Merged into a local dict and published in one assignment, so the
        # event loop never reads a half-updated snapshot and the values owned
        # by the other blocks are preserved.
        data = {**self.data, **decoded}
        data.update(self._derived(data))
        self.data = data
        return True

    @staticmethod
    def _derived(data: Dict[str, Any]) -> Dict[str, Any]:
        """Recompute the values that are not read from any register.

        pv_total_power spans two blocks (the PV strings live in "state", the
        external PV inverter in "grid"), so it is recomputed from the merged
        snapshot after every block instead of inside a single decoder.
        """
        derived: Dict[str, Any] = {}
        pv1 = data.get("pv1_power")
        pv2 = data.get("pv2_power")
        if pv1 is None or pv2 is None:
            return derived

        internal = pv1 + pv2
        derived["pv_internal_total_power"] = internal
        external = data.get("external_pv_power")
        if external is not None:
            derived["pv_total_power"] = internal + external
        return derived

    # -------------------------
    # Decodificadores de bloque
    # -------------------------
    # Each decoder works on its own register window, so the index of a value
    # is relative to the start of the block. They are written as
    # `at(<absolute index>)` to stay directly comparable with the register map.
    def _decode_life(self, registers) -> Dict[str, Any]:
        """30007-30012: lifetime counter, stop code and alarm code."""
        base = 6

        def at(index):
            return registers[index - base]

        return {
            "total_operation_time": self._u32_from_words_le(registers, 6 - base),
            "stop_code": at(9),
            "alarm_code": self._u32_from_words_le(registers, 10 - base),
        }

    def _decode_state(self, registers) -> Dict[str, Any]:
        """30016-30037: inverter status, battery and both PV strings."""
        base = 15

        def at(index):
            return registers[index - base]

        status_code = at(15)
        batt_status_code = at(26)
        batt_limit_code = at(29)
        battery_power = self._decode_signed(at(19))

        return {
            "status": INVERTER_STATUS.get(status_code, f"Unknown ({status_code})"),
            "waiting_time": at(16),
            "battery_voltage": at(17) / 10.0,
            "battery_current": self._decode_signed(at(18)) / 100.0,
            "battery_discharging_power": max(0, battery_power),
            "battery_charging_power": max(0, -battery_power),
            "battery_state_of_charge": at(20),
            "battery_state_of_health": at(21),
            "battery_charging_voltage": at(22) / 10.0,
            "battery_discharging_voltage": at(23) / 10.0,
            "battery_charging_current_max": at(24) / 100.0,
            "battery_discharging_current_max": at(25) / 100.0,
            "battery_status": BATTERY_STATUS.get(
                batt_status_code, f"Unknown ({batt_status_code})"
            ),
            "battery_temp": self._decode_signed(at(27)) / 10.0,
            "battery_bms_alarm": at(28),
            "battery_bms_alarms": self._decode_bms_alarms(at(28)),
            "battery_discharge_limitation_reason": BATTERY_LIMITATION_REASONS.get(
                batt_limit_code, f"Unknown ({batt_limit_code})"
            ),
            "battery_voltage_internal": at(30) / 10.0,
            "pv1_voltage": at(31),
            "pv1_current": at(32) / 100.0,
            "pv1_power": at(33),
            "pv2_voltage": at(34),
            "pv2_current": at(35) / 100.0,
            "pv2_power": at(36),
        }

    def _decode_ac(self, registers) -> Dict[str, Any]:
        """30038-30054: inverter AC, critical loads and the internal meter."""
        base = 37

        def at(index):
            return registers[index - base]

        ap_reason_code = at(41)

        return {
            "active_power": self._decode_signed(at(37)),
            "reactive_power": self._decode_signed(at(38)),
            "power_factor": self._decode_signed(at(39)) / 1000.0,
            "ap_reduction_ratio": at(40) / 10.0,
            "ap_reduction_reason": AP_REDUCTION_REASONS.get(
                ap_reason_code, f"Unknown ({ap_reason_code})"
            ),
            "reactive_setpoint_type": at(42),
            "cl_voltage": at(43),
            "cl_current": at(44) / 100.0,
            "cl_freq": at(45) / 100.0,
            "cl_active_power": self._decode_signed(at(46)),
            "cl_reactive_power": self._decode_signed(at(47)),
            "im_voltage": at(48),
            "im_current": at(49) / 100.0,
            "im_freq": at(50) / 100.0,
            "im_active_power": self._decode_signed(at(51)),
            "im_reactive_power": self._decode_signed(at(52)),
            "im_power_factor": self._decode_signed(at(53)) / 1000.0,
        }

    def _decode_diagnostics(self, registers) -> Dict[str, Any]:
        """30055-30069: DC bus, temperatures, insulation, digital I/O."""
        base = 54

        def at(index):
            return registers[index - base]

        return {
            "dc_bus_voltage": at(54),
            "temp_mod_1": self._decode_signed(at(55)) / 10.0,
            "temp_mod_2": self._decode_signed(at(56)) / 10.0,
            "temp_pcb": self._decode_signed(at(57)) / 10.0,
            "positive_isolation_resistance": at(59),
            "negative_isolation_resistance": at(60),
            "rms_diff_current": at(61) / 10.0,
            "do_1_status": BOOLEAN_STATUS.get(at(62), "Unknown"),
            "do_2_status": BOOLEAN_STATUS.get(at(63), "Unknown"),
            "di_drm_status": BOOLEAN_STATUS.get(at(64), "Unknown"),
            "di_2_status": BOOLEAN_STATUS.get(at(65), "Unknown"),
            "di_3_status": BOOLEAN_STATUS.get(at(66), "Unknown"),
            "battery_bms_flags": at(68),
        }

    def _decode_grid(self, registers) -> Dict[str, Any]:
        """30070-30081: external meter, extended BMS, total loads, PV and EV."""
        base = 69

        def at(index):
            return registers[index - base]

        grid_power = self._decode_signed(at(71))
        batt_charge_limit_code = at(77)

        return {
            "em_voltage": at(69),
            "em_freq": at(70) / 10.0,
            "em_active_power": max(0, grid_power),
            "em_active_power_returned": max(0, -grid_power),
            "em_reactive_power": self._decode_signed(at(72)),
            "battery_bms_warnings": at(73),
            "battery_bms_errors": at(74),
            "battery_bms_faults": at(75),
            "battery_charge_limitation_reason": BATTERY_LIMITATION_REASONS.get(
                batt_charge_limit_code, f"Unknown ({batt_charge_limit_code})"
            ),
            "total_loads_power": at(78),
            "external_pv_power": at(79),
            "ev_power": self._decode_signed(at(80)),
        }
