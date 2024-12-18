"""
Support for the EPH Controls Ember themostats.
Forked from https://www.home-assistant.io/integrations/ephember
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
import time

from .custompyephember.pyephember import (
    EphEmber,
    ZoneMode,
    zone_current_temperature,
    zone_is_active,
    zone_is_boost_active,
    zone_mode,
    zone_name,
    zone_target_temperature,
)
import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_PASSWORD,
    CONF_USERNAME,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback



# Return cached results if last scan was less then this time ago
SCAN_INTERVAL = timedelta(seconds=120)

OPERATION_LIST = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_USERNAME): cv.string, vol.Required(CONF_PASSWORD): cv.string}
)

EPH_TO_HA_STATE = {
    "AUTO": HVACMode.AUTO,
    "ON": HVACMode.HEAT,
    "OFF": HVACMode.OFF,
}

HA_STATE_TO_EPH = {value: key for key, value in EPH_TO_HA_STATE.items()}

import logging
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Set up EphEmber thermostats from a config entry."""
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)

    try:
        # Instantiate EphEmber synchronously
        ember = EphEmber(username, password)

        # Perform async login/setup step
        await ember.async_login()

        # Retrieve zones (ensure this is async if accessing the network)
        zones = await ember.async_get_zones()

        # Create thermostat entities
        entities = [EphEmberThermostat(ember, zone) for zone in zones]
        async_add_entities(entities)
    except Exception as e:
        _LOGGER.error(f"Cannot connect to EphEmber: {repr(e)}")
        return False

    return True


class EphEmberThermostat(ClimateEntity):
    """Representation of a EphEmber thermostat."""

    _attr_hvac_modes = OPERATION_LIST
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, ember, zone):
        """Initialize the thermostat."""
        self._ember = ember
        self._zone_name = zone_name(zone)
        self._zone = zone
        self._hot_water = zone['deviceType'] == 4
        """4 is a specific device type for immersions returned by EPH. Hot Water temp cannot be changed"""
        
        self._attr_name = self._zone_name

        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )
        self._attr_target_temperature_step = 0.5
        if self._hot_water:
            self._attr_supported_features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
            self._attr_target_temperature_step = None

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return zone_current_temperature(self._zone)

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return zone_target_temperature(self._zone)

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action."""
        if zone_is_active(self._zone):
            return HVACAction.HEATING

        return HVACAction.IDLE

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation ie. heat, cool, idle."""
        mode = zone_mode(self._zone)
        return self.map_mode_eph_hass(mode)

    def set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the operation mode."""
        mode = self.map_mode_hass_eph(hvac_mode)
        if mode is not None:
            self._ember.set_zone_mode(self._zone_name, mode)
        else:
            _LOGGER.error("Invalid operation mode provided %s", hvac_mode)

    def turn_on(self):
        self.set_hvac_mode(HVACMode.HEAT)

    def turn_off(self):
        self.set_hvac_mode(HVACMode.OFF)

    @property
    def is_aux_heat(self):
        """Return true if aux heater."""

        return zone_is_boost_active(self._zone)

    def turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        self._ember.activate_zone_boost(
            self._zone_name, zone_target_temperature(self._zone)
        )

    def turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        self._ember.deactivate_zone_boost(self._zone_name)

    def set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        if self._hot_water:
            return

        if temperature == self.target_temperature:
            return

        if temperature > self.max_temp or temperature < self.min_temp:
            return

        self._ember.set_zone_target_temperature(self._zone_name, temperature)

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        # Hot water temp doesn't support being changed
        if self._hot_water:
            return zone_target_temperature(self._zone)
        return 5.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._hot_water:
            return zone_target_temperature(self._zone)
        return 30.0

    def update(self) -> None:
        start_time = time.time()
        _LOGGER.debug("Starting update for zone: %s", self._zone_name)
        try:
            self._zone = self._ember.get_zone(self._zone_name)
            _LOGGER.debug("Zone updated successfully: %s", self._zone)
        except Exception as e:
            _LOGGER.error("Error during update for zone %s: %s", self._zone_name, repr(e))
        finally:
            elapsed_time = time.time() - start_time
            _LOGGER.debug("Update completed for zone: %s in %.2f seconds", self._zone_name, elapsed_time)

    @staticmethod
    def map_mode_hass_eph(operation_mode):
        """Map from Home Assistant mode to eph mode."""
        return getattr(ZoneMode, HA_STATE_TO_EPH.get(operation_mode), None)

    @staticmethod
    def map_mode_eph_hass(operation_mode):
        """Map from eph mode to Home Assistant mode."""
        return EPH_TO_HA_STATE.get(operation_mode.name, HVACMode.HEAT_COOL)