"""Platform for Discovergy sensor integration."""
from datetime import datetime, timedelta
import logging

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_POWER,
    ENERGY_KILO_WATT_HOUR,
    POWER_WATT,
)
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, NAME, SUPPORTED_METER_TYPES

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=3)

CONF_ENERGY = "energy"
CONF_POWER = "power"

DEFAULT_SENSORS = [CONF_ENERGY, CONF_POWER]

SENSOR_TYPES = {
    CONF_ENERGY: {
        "name": "Energy Consumed",
        "unit": ENERGY_KILO_WATT_HOUR,
        "class": DEVICE_CLASS_ENERGY,
        "api_name": "energy",
        "scale": 1 / 10 ** 10,
    },
    CONF_POWER: {
        "name": "Power",
        "unit": POWER_WATT,
        "class": DEVICE_CLASS_POWER,
        "api_name": "power",
        "scale": 1 / 1000,
    },
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Discovergy sensors."""

    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]

    api = hass.data[DOMAIN][config_entry.entry_id]
    await hass.async_add_executor_job(api.login, username, password)

    # Get all associated smart-meters for the provided account
    account_meters_info = await hass.async_add_executor_job(api.get_meters)
    if not account_meters_info:
        return False

    account_meters_info = {
        d.get("meterId"): {
            "location": d.get("location"),
        }
        for d in account_meters_info
        if d.get("measurementType") in SUPPORTED_METER_TYPES
    }

    entities = []
    for meter_id, meter_data in account_meters_info.items():
        for sensor_type in DEFAULT_SENSORS:
            entities.append(
                DiscovergyMeterSensor(
                    hass,
                    api,
                    username,
                    password,
                    meter_id,
                    sensor_type,
                    meter_data["location"],
                )
            )
    async_add_entities(entities, True)

    return True


class DiscovergyMeterSensor(Entity):
    """Implementation of Discovergy meter sensor."""

    def __init__(self, hass, api, username, password, meter_id, sensor_type, location):
        """Initialize the sensor."""

        self.hass = hass
        self.api = api
        self.username = username
        self.password = password
        self.meter_id = meter_id
        self._state = None
        self._attrs = {"location": location}
        self._name = f"{SENSOR_TYPES[sensor_type]['name']}"
        self._unit_of_measurement = SENSOR_TYPES[sensor_type]["unit"]
        self._scale = SENSOR_TYPES[sensor_type]["scale"]
        self.sensor_type = sensor_type
        self.api_sensor_type = SENSOR_TYPES[sensor_type]["api_name"]

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {
            "identifiers": {(DOMAIN, f"discovergy_smart_meter_{self.username}")},
            "name": f"{NAME}_{self.meter_id}",
            "manufacturer": MANUFACTURER,
        }

    @property
    def unique_id(self):
        """Return a unique_id for this entity."""
        return f"{self.meter_id}_{self.sensor_type}"

    @property
    def device_class(self):
        """Return the device class."""
        return SENSOR_TYPES[self.sensor_type]["class"]

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the state attributes."""

        return self._attrs

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of the sensor."""
        return self._unit_of_measurement

    async def async_update(self):
        """Update meter data."""
        try:
            # self.api.login(email=self.username, password=self.password)
            await self.hass.async_add_executor_job(
                self.api.login, self.username, self.password
            )
            _LOGGER.debug("Updating data for %s", self.meter_id)

            # Power and voltage are instantaneous measurements, however energy is the cumulative,
            # therefore we need to take the delta between 'now' and a previous time point
            # to get the energy consumption in the last time range.
            now = datetime.now()
            now = int(now.timestamp() * 1000)  # timestamp in milliseconds

            sensor_data = await self.hass.async_add_executor_job(
                self.api.get_readings,
                self.meter_id,
                now - (6 * 60 * 1000),  # start time: 6min ago
                now,  # end time
                "three_minutes",  # time resolution
                str(self.api_sensor_type),  # sensor types
            )

            time_sorted_data = [(d["time"], d["values"]) for d in sensor_data]
            time_sorted_data.sort(key=lambda x: x[0], reverse=True)

            if self.sensor_type == CONF_ENERGY:
                reading = (
                    time_sorted_data[0][1][self.api_sensor_type]
                    - time_sorted_data[1][1][self.api_sensor_type]
                )
            else:
                reading = time_sorted_data[0][1][self.api_sensor_type]
            self._state = reading * self._scale
            _LOGGER.info(
                "Discovergy meter %s: %s",
                self.name,
                self.state,
            )
        except (ValueError, KeyError, IndexError):
            _LOGGER.warning("Could not update status for %s", self.name)
