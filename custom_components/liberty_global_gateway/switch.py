"""Switch platform for the Liberty Global cable gateway integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from liberty_global_gateway import LibertyGatewayClient
from liberty_global_gateway.exceptions import GatewayError

from . import GatewayDataUpdateCoordinator
from .const import DOMAIN
from .entity import GatewayEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GatewaySwitchDescription(SwitchEntityDescription):
    """Describes a gateway switch: how to read it and how to set it."""

    value_fn: Callable[[dict], bool | None]
    set_fn: Callable[[LibertyGatewayClient, bool], Awaitable[None]]


# Only connectivity-safe toggles: nothing here can drop your internet or Wi-Fi.
SWITCHES: tuple[GatewaySwitchDescription, ...] = (
    GatewaySwitchDescription(
        key="upnp",
        translation_key="upnp_switch",
        icon="mdi:upload-network",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: d.get("upnp"),
        set_fn=lambda client, on: client.set_upnp(on),
    ),
    GatewaySwitchDescription(
        key="led_auto",
        translation_key="led_auto",
        icon="mdi:led-on",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: getattr(d.get("led"), "automode", None),
        set_fn=lambda client, on: client.set_led(automode=on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches from a config entry."""
    coordinator: GatewayDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities(
        GatewaySwitch(coordinator, config_entry.entry_id, description)
        for description in SWITCHES
    )


class GatewaySwitch(GatewayEntity, SwitchEntity):
    """A writable gateway setting exposed as a switch."""

    entity_description: GatewaySwitchDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        entry_id: str,
        description: GatewaySwitchDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    async def _apply(self, turn_on: bool) -> None:
        client = self.coordinator.client
        try:
            await client.login()
            await self.entity_description.set_fn(client, turn_on)
        except GatewayError as err:
            raise HomeAssistantError(
                f"Could not update {self.entity_description.key}: {err}"
            ) from err
        finally:
            await client.logout()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._apply(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._apply(False)
