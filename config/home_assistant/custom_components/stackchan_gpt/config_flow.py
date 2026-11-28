"""Add a single StackChan GPT conversation agent."""

from homeassistant import config_entries

from . import DOMAIN


class StackChanGPTConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="StackChan GPT", data={})
