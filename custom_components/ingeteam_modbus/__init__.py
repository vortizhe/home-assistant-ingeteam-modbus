"""The Ingeteam Modbus Integration."""
import asyncio
import logging
import threading
from datetime import timedelta
from typing import Optional

import voluptuous as vol
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from .const import (
    DOMAIN,
    DEFAULT_NAME,
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
    AP_REDUCTION_REASONS
)

_LOGGER = logging.getLogger(__name__)

INGETEAM_MODBUS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.string,
        vol.Optional(CONF_MODBUS_ADDRESS, default=DEFAULT_MODBUS_ADDRESS): cv.positive_int,
        vol.Optional(CONF_READ_METER, default=DEFAULT_READ_METER): cv.boolean,
        vol.Optional(CONF_READ_BATTERY, default=DEFAULT_READ_BATTERY): cv.boolean,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): cv.positive_int,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: INGETEAM_MODBUS_SCHEMA})}, extra=vol.ALLOW_EXTRA
)

PLATFORMS = ["sensor"]


async def async_setup(hass, config):
    """Set up the Ingeteam modbus component."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a ingeteam mobus."""
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    port = entry.data[CONF_PORT]
    address = entry.data.get(CONF_MODBUS_ADDRESS, 1)
    scan_interval = entry.data[CONF_SCAN_INTERVAL]
    read_meter = entry.data.get(CONF_READ_METER, False)
    read_battery = entry.data.get(CONF_READ_BATTERY, False)

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)

    hub = IngeteamModbusHub(
        hass, name, host, port, address, scan_interval, read_meter, read_battery
    )
    """Register the hub."""
    hass.data[DOMAIN][name] = {"hub": hub}

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )
    return True


async def async_unload_entry(hass, entry):
    """Unload Ingeteam mobus entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if not unload_ok:
        return False

    hass.data[DOMAIN].pop(entry.data["name"])
    return True

class IngeteamModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass,
        name,
        host,
        port,
        address,
        scan_interval,
        read_meter=True,
        read_battery=False,
    ):
        """Initialize the Modbus hub."""
        self._hass = hass
        self._client = ModbusTcpClient(host=host, port=port)
        self._lock = threading.Lock()
        self._name = name
        self._address = address
        self.read_meter = read_meter
        self.read_battery = read_battery
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensors = []
        self.data = {}

    @callback
    def async_add_ingeteam_sensor(self, update_callback):
        """Listen for data updates."""
        # This is the first sensor, set up interval.
        if not self._sensors:
            self.connect()
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_refresh_modbus_data, self._scan_interval
            )

        self._sensors.append(update_callback)

    @callback
    def async_remove_ingeteam_sensor(self, update_callback):
        """Remove data update."""
        self._sensors.remove(update_callback)

        if not self._sensors:
            """stop the interval timer upon removal of last sensor"""
            self._unsub_interval_method()
            self._unsub_interval_method = None
            self.close()

    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> None:
        """Time to update."""
        if not self._sensors:
            return

        try:
            update_result = self.read_modbus_data()
        except Exception as e:
            _LOGGER.exception("Error reading modbus data")
            update_result = False

        if update_result:
            for update_callback in self._sensors:
                update_callback()

    @property
    def name(self):
        """Return the name of this hub."""
        return self._name

    def close(self):
        """Disconnect client."""
        with self._lock:
            self._client.close()

    def connect(self):
        """Connect client."""
        with self._lock:
            self._client.connect()

    @property
    def has_meter(self):
        """Return true if a meter is available"""
        return self.read_meter

    @property
    def has_battery(self):
        """Return true if a battery is available"""
        return self.read_battery

    def read_input_registers(self, unit, address, count):
        """Read input registers."""
        with self._lock:
            kwargs = {"unit": unit} if unit else {}
            return self._client.read_input_registers(address, count, **kwargs, slave=1)


    def read_modbus_data(self):
        return (
            self.read_modbus_data_status()
            and self.read_modbus_data_inverter()
            and self.read_modbus_data_meter()
            and self.read_modbus_data_pv_field()
            and self.read_modbus_data_battery()
        )

    def read_modbus_data_status(self):
        status_data = self.read_input_registers(unit=self._address, address=9, count=8)
        if status_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            status_data.registers, byteorder=Endian.Big
        )

        stop_code = decoder.decode_16bit_uint()
        alarm_code = decoder.decode_32bit_uint()
        decoder.skip_bytes(6)
        # alarm_code_1 = decoder.decode_16bit_uint()
        # alarm_code_2 = decoder.decode_16bit_uint()
        # alarm_code_3 = decoder.decode_16bit_uint()
        status = decoder.decode_16bit_uint()
        waiting_time = decoder.decode_16bit_uint()

        self.data["stop_code"] = stop_code
        self.data["alarm_code"] = alarm_code
        # self.data["alarm_code_1"] = alarm_code_1
        # self.data["alarm_code_2"] = alarm_code_2
        # self.data["alarm_code_3"] = alarm_code_3
        self.data["waiting_time"] = waiting_time

        if status in INVERTER_STATUS:
            self.data['status'] = INVERTER_STATUS[status]
        else:
            self.data['status'] = status

        return True
    
    def read_modbus_data_inverter(self):
        status_data = self.read_input_registers(unit=self._address, address=37, count=30)
        if status_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            status_data.registers, byteorder=Endian.Big
        )

        active_power = decoder.decode_16bit_int()
        reactive_power = decoder.decode_16bit_int()
        power_factor = decoder.decode_16bit_int()
        ap_reduction_ratio = decoder.decode_16bit_uint()
        ap_reduction_reason = decoder.decode_16bit_uint()
        reactive_setpoint_type = decoder.decode_16bit_uint()
        cl_voltage = decoder.decode_16bit_uint()
        cl_current = decoder.decode_16bit_uint()
        cl_freq = decoder.decode_16bit_uint()
        cl_active_power = decoder.decode_16bit_int()
        cl_reactive_power = decoder.decode_16bit_int()
        im_voltage = decoder.decode_16bit_uint()
        im_current = decoder.decode_16bit_uint()
        im_freq = decoder.decode_16bit_uint()
        im_active_power = decoder.decode_16bit_int()
        im_reactive_power = decoder.decode_16bit_int()
        im_power_factor = decoder.decode_16bit_int()
        dc_bus_voltage = decoder.decode_16bit_uint()
        decoder.skip_bytes(4)
        internal_temp = decoder.decode_16bit_int()
        decoder.skip_bytes(6)
        rms_diff_current = decoder.decode_16bit_uint()
        do_1_status = decoder.decode_16bit_uint()
        do_2_status = decoder.decode_16bit_uint()
        di_drm_status = decoder.decode_16bit_uint()
        di_2_status = decoder.decode_16bit_uint()
        di_3_status = decoder.decode_16bit_uint()

        self.data["active_power"] = active_power
        self.data["reactive_power"] = reactive_power
        self.data["power_factor"] = power_factor / 1000
        self.data["ap_reduction_ratio"] = ap_reduction_ratio / 10
        self.data["ap_reduction_reason"] = ap_reduction_reason
        if ap_reduction_reason in AP_REDUCTION_REASONS:
            self.data['ap_reduction_reason'] = AP_REDUCTION_REASONS[ap_reduction_reason]
        else:
            self.data['ap_reduction_reason'] = ap_reduction_reason
        self.data["reactive_setpoint_type"] = reactive_setpoint_type
        self.data["cl_voltage"] = cl_voltage
        self.data["cl_current"] = cl_current / 100
        self.data["cl_freq"] = cl_freq / 100
        self.data["cl_active_power"] = cl_active_power
        self.data["cl_reactive_power"] = cl_reactive_power
        self.data["im_voltage"] = im_voltage
        self.data["im_current"] = im_current / 100
        self.data["im_freq"] = im_freq / 100
        self.data["im_active_power"] = im_active_power
        self.data["im_reactive_power"] = im_reactive_power
        self.data["im_power_factor"] = im_power_factor / 1000
        self.data["dc_bus_voltage"] = dc_bus_voltage
        self.data["internal_temp"] = internal_temp / 10
        self.data["rms_diff_current"] = rms_diff_current
        self.data["do_1_status"] = BOOLEAN_STATUS[do_1_status] 
        self.data["do_2_status"] = BOOLEAN_STATUS[do_2_status]
        self.data["di_drm_status"] = BOOLEAN_STATUS[di_drm_status]
        self.data["di_2_status"] = BOOLEAN_STATUS[di_2_status]
        self.data["di_3_status"] = BOOLEAN_STATUS[di_3_status]

        return True

    def read_modbus_data_meter(self):
        """start reading meter  data """
        meter_data = self.read_input_registers(unit=self._address, address=69, count=4)
        if meter_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            meter_data.registers, byteorder=Endian.Big
        )
        
        em_voltage = decoder.decode_16bit_uint()
        em_freq = decoder.decode_16bit_uint()
        em_active_power_data = decoder.decode_16bit_int()
        em_active_power = round(em_active_power_data, abs(em_active_power_data))
        em_reactive_power = decoder.decode_16bit_int()

        self.data["em_voltage"] = round(em_voltage, abs(em_voltage))
        self.data["em_freq"] = round(em_freq / 10)
        self.data["em_active_power"] = em_active_power if em_active_power >= 0 else 0
        self.data["em_active_power_returned"] = em_active_power * -1 if em_active_power < 0 else 0
        self.data["em_reactive_power"] = round(em_reactive_power, abs(em_reactive_power))

        return True


    def read_modbus_data_pv_field(self):
        inverter_data = self.read_input_registers(unit=self._address, address=31, count=6)
        if inverter_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            inverter_data.registers, byteorder=Endian.Big
        )

        pv1_voltage = decoder.decode_16bit_uint()
        pv1_current = decoder.decode_16bit_uint()
        pv1_power = decoder.decode_16bit_uint()
        pv2_voltage = decoder.decode_16bit_uint()
        pv2_current = decoder.decode_16bit_uint()
        pv2_power = decoder.decode_16bit_uint()

        self.data["pv1_voltage"] = pv1_voltage 
        self.data["pv1_current"] = pv1_current / 100
        self.data["pv1_power"] = pv1_power
        self.data["pv2_voltage"] = pv2_voltage
        self.data["pv2_current"] = pv2_current / 100
        self.data["pv2_power"] = pv2_power

        self.data["pv_total_power"] = pv1_power + pv2_power

        return True

    def read_modbus_data_battery(self):
        battery_data = self.read_input_registers(unit=self._address, address=17, count=14)
        if battery_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            battery_data.registers, byteorder=Endian.Big,wordorder=Endian.Little
        )

        battery_voltage = decoder.decode_16bit_uint()
        battery_current = decoder.decode_16bit_int()
        battery_power = decoder.decode_16bit_int()
        battery_state_of_charge = decoder.decode_16bit_uint()
        battery_state_of_health = decoder.decode_16bit_uint()
        battery_charging_voltage = decoder.decode_16bit_uint()
        battery_discharging_voltage = decoder.decode_16bit_uint()
        battery_charging_current_max = decoder.decode_16bit_uint()
        battery_discharging_current_max = decoder.decode_16bit_uint()
        battery_status = decoder.decode_16bit_uint()
        battery_temp = decoder.decode_16bit_int()
        battery_bms_alarm = decoder.decode_16bit_uint()
        battery_discharge_limitation_reason = decoder.decode_16bit_uint()
        battery_voltage_internal = decoder.decode_16bit_uint()


        self.data["battery_voltage"] = battery_voltage / 10
        self.data["battery_current"] = battery_current / 100
        self.data["battery_discharging_power"] = battery_power if battery_power > 0 else 0
        self.data["battery_charging_power"] = battery_power * -1 if battery_power < 0 else 0
        self.data["battery_state_of_charge"] = battery_state_of_charge
        self.data["battery_state_of_health"] = battery_state_of_health
        self.data["battery_charging_voltage"] = battery_charging_voltage / 10
        self.data["battery_discharging_voltage"] = battery_discharging_voltage / 10
        self.data["battery_charging_current_max"] = battery_charging_current_max / 100
        self.data["battery_discharging_current_max"] = battery_discharging_current_max / 100
        self.data["battery_temp"] = battery_temp / 10
        self.data["battery_voltage_internal"] = battery_voltage_internal / 10
        self.data['battery_status'] = BATTERY_STATUS[battery_status]
        self.data['battery_bms_alarm'] = BATTERY_BMS_ALARMS[battery_bms_alarm]
        self.data['battery_discharge_limitation_reason'] = BATTERY_LIMITATION_REASONS[battery_discharge_limitation_reason]

        # Some attr are bugged in certain statuses
        if battery_status == 7:
            self.data['battery_voltage'] = 0
            self.data['battery_current'] = 0
            self.data['battery_power'] = 0
            self.data['battery_charging_current_max'] = 0
            self.data['battery_discharging_current_max'] = 0
            self.data['battery_bms_alarm'] = "None"

        return True
