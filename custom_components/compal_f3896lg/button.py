"""Button platform for the Compal / Sagemcom F3896LG integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from compalf3896lg.exceptions import CompalError

from . import CompalDataUpdateCoordinator
from .const import DOMAIN
from .entity import CompalEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the reboot button from a config entry."""
    coordinator: CompalDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities([CompalRebootButton(coordinator, config_entry.entry_id)])


class CompalRebootButton(CompalEntity, ButtonEntity):
    """Reboot the gateway (drops the WAN for a minute or two)."""

    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: CompalDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the reboot button."""
        super().__init__(coordinator, entry_id, "reboot")

    async def async_press(self) -> None:
        """Log in, issue a reboot, then release the session slot."""
        client = self.coordinator.client
        try:
            await client.login()
            await client.reboot()
        except CompalError as err:
            raise HomeAssistantError(f"Could not reboot the gateway: {err}") from err
        finally:
            await client.logout()
