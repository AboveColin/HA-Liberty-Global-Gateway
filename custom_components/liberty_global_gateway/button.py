"""Button platform for the Liberty Global cable gateway integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from liberty_global_gateway.exceptions import GatewayError

from . import GatewayDataUpdateCoordinator
from .const import DOMAIN
from .entity import GatewayEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the reboot button from a config entry."""
    coordinator: GatewayDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities([GatewayRebootButton(coordinator, config_entry.entry_id)])


class GatewayRebootButton(GatewayEntity, ButtonEntity):
    """Reboot the gateway (drops the WAN for a minute or two)."""

    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: GatewayDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the reboot button."""
        super().__init__(coordinator, entry_id, "reboot")

    async def async_press(self) -> None:
        """Log in, issue a reboot, then release the session slot."""
        try:
            async with self.coordinator.session():
                await self.coordinator.client.reboot()
        except GatewayError as err:
            raise HomeAssistantError(f"Could not reboot the gateway: {err}") from err
