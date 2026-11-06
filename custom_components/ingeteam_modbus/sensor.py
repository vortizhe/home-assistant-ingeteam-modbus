"""Sensor platform for the Ingeteam Modbus integration."""
import inspect
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.components.integration.const import METHOD_TRAPEZOIDAL
from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.util import slugify

from .const import (
    ATTR_MANUFACTURER,
    BATTERY_SENSOR_TYPES,
    DOMAIN,
    INVERTER_SENSOR_TYPES,
    INVERTER_STATUS_TYPES,
    METER_SENSOR_TYPES,
    PV_FIELD_SENSOR_TYPES,
    TEXT_SENSOR_KEYS,
    TOTAL_INCREASING_KEYS,
)

_LOGGER = logging.getLogger(__name__)

# The integration sensors are forced to update at least this often so that a
# constant power reading keeps accumulating energy.
MAX_SUB_INTERVAL = timedelta(seconds=60)

# Unit code used in const.py -> (native unit, device class)
UNIT_MAP: dict[str, tuple[Optional[str], Optional[SensorDeviceClass]]] = {
    "A": (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    "mA": (UnitOfElectricCurrent.MILLIAMPERE, SensorDeviceClass.CURRENT),
    "V": (UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    "W": (UnitOfPower.WATT, SensorDeviceClass.POWER),
    "Var": (UnitOfReactivePower.VOLT_AMPERE_REACTIVE, SensorDeviceClass.REACTIVE_POWER),
    "kWh": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "Hz": (UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY),
    "C": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "B": (PERCENTAGE, SensorDeviceClass.BATTERY),
    "%": (PERCENTAGE, None),
    "s": (UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
    "h": (UnitOfTime.HOURS, SensorDeviceClass.DURATION),
    "kOhm": ("kΩ", None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Ingeteam sensors from a config entry."""
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    # Entity ids are built by Home Assistant from the slugified friendly name,
    # so the source entity of an integration sensor has to be slugified too.
    hub_slug = slugify(hub_name)

    def build(sensor_types):
        """Create the entities described by one of the const.py tables.

        A table row is [friendly name, data key, unit code, icon] and, when it
        has a fifth element, the slug of the power sensor whose value has to be
        integrated to obtain this (energy) sensor.
        """
        built = []
        for sensor_info in sensor_types.values():
            if len(sensor_info) > 4:
                built.append(
                    CalculatedEnergySensor(
                        hub,
                        name=f"{hub_name} {sensor_info[0]}",
                        source_entity=f"sensor.{hub_slug}_{slugify(sensor_info[4])}",
                        unique_id=f"{hub_name}_{sensor_info[1]}",
                        device_info=device_info,
                        icon=sensor_info[3],
                    )
                )
            else:
                built.append(
                    IngeteamSensor(
                        hub_name,
                        hub,
                        device_info,
                        sensor_info[0],
                        sensor_info[1],
                        sensor_info[2],
                        sensor_info[3],
                    )
                )
        return built

    entities = []
    entities += build(INVERTER_STATUS_TYPES)
    entities += build(INVERTER_SENSOR_TYPES)
    entities += build(PV_FIELD_SENSOR_TYPES)
    if hub.read_meter:
        entities += build(METER_SENSOR_TYPES)
    if hub.read_battery:
        entities += build(BATTERY_SENSOR_TYPES)

    async_add_entities(entities)
    return True


class CalculatedEnergySensor(IntegrationSensor):
    """Energy sensor obtained by integrating one of the hub's power sensors."""

    def __init__(
        self,
        hub,
        *,
        name: str | None,
        source_entity: str,
        unique_id: str | None,
        device_info: Optional[Dict[str, Any]] = None,
        icon: str | None = None,
        integration_method: str = METHOD_TRAPEZOIDAL,
        max_sub_interval: timedelta | None = MAX_SUB_INTERVAL,
    ) -> None:
        """Initialize the integration sensor."""
        kwargs: dict[str, Any] = {
            "integration_method": integration_method,
            "name": name,
            "round_digits": 2,
            "source_entity": source_entity,
            "unique_id": unique_id,
            "device_class": SensorDeviceClass.ENERGY,
            "unit_prefix": "k",
            "unit_time": UnitOfTime.HOURS,
            "max_sub_interval": max_sub_interval,
        }

        # IntegrationSensor is core-internal API and its signature changes
        # between Home Assistant releases: only forward what it accepts.
        params = inspect.signature(IntegrationSensor.__init__).parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            dropped = [key for key in kwargs if key not in params]
            if dropped:
                _LOGGER.debug("IntegrationSensor does not accept %s, skipping", dropped)
            kwargs = {k: v for k, v in kwargs.items() if k in params}

        super().__init__(**kwargs)

        self._attr_icon = icon or "mdi:chart-histogram"
        if device_info is not None:
            self._attr_device_info = device_info
        self._hub = hub

    @property
    def hub(self):
        """Return the Modbus hub this sensor belongs to."""
        return self._hub


class IngeteamSensor(SensorEntity):
    """Representation of an Ingeteam Modbus sensor."""

    _attr_should_poll = False

    def __init__(self, platform_name, hub, device_info, name, key, unit, icon):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._hub = hub
        self._key = key
        self._attr_name = f"{platform_name} {name}"
        self._attr_unique_id = f"{platform_name}_{key}"
        self._attr_icon = icon
        self._attr_device_info = device_info

        native_unit, device_class = UNIT_MAP.get(unit, (unit, None))
        self._attr_native_unit_of_measurement = native_unit
        self._attr_device_class = device_class
        self._attr_state_class = self._state_class_for(key, device_class)

    @staticmethod
    def _state_class_for(key, device_class):
        """Pick a state class that Home Assistant accepts for this device class.

        A textual state must carry none at all, and DEVICE_CLASS_STATE_CLASSES
        rejects MEASUREMENT for the energy device class.
        """
        if key in TEXT_SENSOR_KEYS:
            return None
        if device_class is SensorDeviceClass.ENERGY or key in TOTAL_INCREASING_KEYS:
            return SensorStateClass.TOTAL_INCREASING
        return SensorStateClass.MEASUREMENT

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._hub.async_add_ingeteam_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        self._hub.async_remove_ingeteam_sensor(self._modbus_data_updated)

    @callback
    def _modbus_data_updated(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the value of the sensor."""
        return self._hub.data.get(self._key)
