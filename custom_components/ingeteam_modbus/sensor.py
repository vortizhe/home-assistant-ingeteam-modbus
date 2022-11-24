import logging
from typing import Optional, Dict, Any
from decimal import Decimal
from .const import (
    INVERTER_STATUS_TYPES,
    INVERTER_SENSOR_TYPES,
    METER_SENSOR_TYPES,
    PV_FIELD_SENSOR_TYPES,
    BATTERY_SENSOR_TYPES,
    DOMAIN,
    ATTR_MANUFACTURER,
)
from homeassistant.const import CONF_NAME, DEVICE_CLASS_ENERGY, ENERGY_KILO_WATT_HOUR, CONF_SCAN_INTERVAL
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    STATE_CLASS_MEASUREMENT,
    SensorEntity,
)
from homeassistant.components.integration.sensor import IntegrationSensor,ATTR_SOURCE_ID,UNIT_PREFIXES,UNIT_TIME


from homeassistant.core import callback
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities = []
    for sensor_info in INVERTER_STATUS_TYPES.values():
        sensor = IngeteamSensor(
            hub_name,
            hub,
            device_info,
            sensor_info[0],
            sensor_info[1],
            sensor_info[2],
            sensor_info[3],
        )
        entities.append(sensor)
    
    for sensor_info in INVERTER_SENSOR_TYPES.values():
        if len(sensor_info) > 4 :
            sensor = CalculatedEnergySensor(
                hub,
                name=f'{hub_name} {sensor_info[0]}', 
                source_entity=f'sensor.{hub_name}_{sensor_info[4]}',
                unique_id=f'{hub_name}_{sensor_info[1]}',
            )
        else:  
            sensor = IngeteamSensor(
                hub_name,
                hub,
                device_info,
                sensor_info[0],
                sensor_info[1],
                sensor_info[2],
                sensor_info[3],
            )
        entities.append(sensor)

    for sensor_info in PV_FIELD_SENSOR_TYPES.values():
        if len(sensor_info) > 4 :
            sensor = CalculatedEnergySensor(
                hub,
                name=f'{hub_name} {sensor_info[0]}', 
                source_entity=f'sensor.{hub_name}_{sensor_info[4]}',
                unique_id=f'{hub_name}_{sensor_info[1]}',
            )
        else:   
            sensor = IngeteamSensor(
                hub_name,
                hub,
                device_info,
                sensor_info[0],
                sensor_info[1],
                sensor_info[2],
                sensor_info[3],
            )
        entities.append(sensor)

    if hub.read_meter == True:
        for sensor_info in METER_SENSOR_TYPES.values():
            if len(sensor_info) > 4 :
                sensor = CalculatedEnergySensor(
                    hub,
                    name=f'{hub_name} {sensor_info[0]}', 
                    source_entity=f'sensor.{hub_name}_{sensor_info[4]}',
                    unique_id=f'{hub_name}_{sensor_info[1]}',
                )
            else:    
                sensor = IngeteamSensor(
                    hub_name,
                    hub,
                    device_info,
                    sensor_info[0],
                    sensor_info[1],
                    sensor_info[2],
                    sensor_info[3],
                )
            entities.append(sensor)

    if hub.read_battery == True:
        for sensor_info in BATTERY_SENSOR_TYPES.values():
            if len(sensor_info) > 4 :
                sensor = CalculatedEnergySensor(
                    hub,
                    name=f'{hub_name} {sensor_info[0]}', 
                    source_entity=f'sensor.{hub_name}_{sensor_info[4]}',
                    unique_id=f'{hub_name}_{sensor_info[1]}',
                )
            else:    
                sensor = IngeteamSensor(
                    hub_name,
                    hub,
                    device_info,
                    sensor_info[0],
                    sensor_info[1],
                    sensor_info[2],
                    sensor_info[3],
                )
            entities.append(sensor)

    async_add_entities(entities)
    return True


class CalculatedEnergySensor(IntegrationSensor):
    def __init__(
        self,
        *
        hub,
        name: str | None,
        source_entity: str,
        unique_id: str | None):
        """Initialize the integration sensor."""
        unit_prefix = "k"
        unit_time = "h"
        self._attr_unique_id = unique_id
        self._sensor_source_id = source_entity
        self._round_digits = 2
        self._state: Decimal | None = None
        self._method = "trapezoidal"

        self._attr_name = name if name is not None else f"{source_entity} integral"
        self._unit_template = f"{'' if unit_prefix is None else unit_prefix}{{}}"
        self._unit_of_measurement: str | None = None
        self._unit_prefix = UNIT_PREFIXES[unit_prefix]
        self._unit_time = UNIT_TIME[unit_time]
        self._unit_time_str = unit_time
        self._attr_icon = "mdi:chart-histogram"
        self._attr_extra_state_attributes = {ATTR_SOURCE_ID: source_entity}
        self._hub = hub

    @property
    def hub(self):
        return self._hub


class IngeteamSensor(SensorEntity):
    """Representation of an Ingeteam Modbus sensor."""

    def __init__(self, platform_name, hub, device_info, name, key, unit, icon):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._hub = hub
        self._key = key
        self._name = name
        self._unit_of_measurement = unit
        self._icon = icon
        self._device_info = device_info
        self._attr_state_class = STATE_CLASS_MEASUREMENT

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._hub.async_add_ingeteam_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_ingeteam_sensor(self._modbus_data_updated)

    @callback
    def _modbus_data_updated(self):
        self.async_write_ha_state()

    @callback
    def _update_state(self):
        if self._key in self._hub.data:
            self._state = self._hub.data[self._key]

    @property
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
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

    @property
    def should_poll(self) -> bool:
        """Data is delivered by the hub"""
        return False

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        return self._device_info
