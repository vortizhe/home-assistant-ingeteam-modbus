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
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback

from .const import (
    ATTR_MANUFACTURER,
    BATTERY_SENSOR_TYPES,
    DOMAIN,
    INVERTER_SENSOR_TYPES,
    INVERTER_STATUS_TYPES,
    METER_SENSOR_TYPES,
    PV_FIELD_SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Ingeteam sensors from a config entry."""
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    def build(sensor_types):
        """Create the entities described by one of the const.py tables.

        A table row is [friendly name, data key, unit, icon] and, when it has a
        fifth element, the slug of the power sensor whose value has to be
        integrated to obtain this (energy) sensor.
        """
        built = []
        for sensor_info in sensor_types.values():
            if len(sensor_info) > 4:
                built.append(
                    CalculatedEnergySensor(
                        hub,
                        name=f"{hub_name} {sensor_info[0]}",
                        source_entity=f"sensor.{hub_name}_{sensor_info[4]}",
                        unique_id=f"{hub_name}_{sensor_info[1]}",
                        device_info=device_info,
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


_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    "A": SensorEntityDescription(
        key="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "V": SensorEntityDescription(
        key="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "W": SensorEntityDescription(
        key="W",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "Var": SensorEntityDescription(
        key="Var",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "B": SensorEntityDescription(
        key="B",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    "C": SensorEntityDescription(
        key="C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    "Hz": SensorEntityDescription(
        key="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "%": SensorEntityDescription(
        key="%",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
}

DIAG_SENSOR = SensorEntityDescription(
    key="_",
    state_class=SensorStateClass.MEASUREMENT,
)


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
        integration_method: str = METHOD_TRAPEZOIDAL,
        max_sub_interval: timedelta | None = None,
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

        self._attr_icon = "mdi:chart-histogram"
        if device_info is not None:
            self._attr_device_info = device_info
        self._hub = hub

    @property
    def hub(self):
        """Return the Modbus hub this sensor belongs to."""
        return self._hub


class IngeteamSensor(SensorEntity):
    """Representation of an Ingeteam Modbus sensor."""

    def __init__(self, platform_name, hub, device_info, name, key, unit, icon):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._hub = hub
        self._key = key
        self._name = name
        self._unit_of_measurement = unit if unit != "B" else "%"
        self._icon = icon
        self._device_info = device_info
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self.entity_description = _DESCRIPTIONS.get(unit, DIAG_SENSOR)

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
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
        """Return the unique id."""
        return f"{self._platform_name}_{self._key}"

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._key in self._hub.data:
            return self._hub.data[self._key]
        return None

    @property
    def should_poll(self) -> bool:
        """Data is delivered by the hub."""
        return False

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return the device info."""
        return self._device_info
