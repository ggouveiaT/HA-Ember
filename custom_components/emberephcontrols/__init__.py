from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EphEmber integration from a config entry."""
    await hass.config_entries.async_forward_entry_setup(entry, "climate")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload EphEmber config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "climate")
    return unload_ok
