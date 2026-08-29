"""Number platform for the Liberty Global cable gateway integration (LED brightness)."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up the LED brightness number from a config entry."""
    coordinator: GatewayDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities([GatewayLedBrightness(coordinator, config_entry.entry_id)])


class GatewayLedBrightness(GatewayEntity, NumberEntity):
    """Front-panel LED brightness (0-100)."""

    _attr_translation_key = "led_brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: GatewayDataUpdateCoordinator, entry_id: str
    ) -> None:
        """Initialize the LED brightness number."""
        super().__init__(coordinator, entry_id, "led_brightness")

    @property
    def native_value(self) -> float | None:
        """Return the current LED brightness."""
        led = (self.coordinator.data or {}).get("led")
        return getattr(led, "brightness", None)

    async def async_set_native_value(self, value: float) -> None:
        """Set the LED brightness."""
        try:
            async with self.coordinator.session():
                await self.coordinator.client.set_led(brightness=int(value))
        except GatewayError as err:
            raise HomeAssistantError(f"Could not set LED brightness: {err}") from err
        await self.coordinator.async_request_refresh()
