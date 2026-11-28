"""Load the local StackChan GPT conversation platform."""

from homeassistant.const import Platform

DOMAIN = "stackchan_gpt"
PLATFORMS = [Platform.CONVERSATION]


async def async_setup_entry(hass, entry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
