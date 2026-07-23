"""Binary sensor platform for the Compal / Sagemcom F3896LG integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CompalDataUpdateCoordinator
from .const import DOMAIN
from .entity import CompalEntity


def _wifi_up(band: str) -> Callable[[dict], bool | None]:
    def _fn(data: dict) -> bool | None:
        state = (data.get("wifi_states") or {}).get(band)
        return None if state is None else state.up

    return _fn


@dataclass(frozen=True, kw_only=True)
class CompalBinaryDescription(BinarySensorEntityDescription):
    """Describes a Compal binary sensor and how to read its state."""

    value_fn: Callable[[dict], bool | None]


BINARY_SENSORS: tuple[CompalBinaryDescription, ...] = (
    CompalBinaryDescription(
        key="modem_operational",
        translation_key="modem_operational",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: getattr(d.get("cable"), "operational", None),
    ),
    CompalBinaryDescription(
        key="bridge_mode",
        translation_key="bridge_mode",
        icon="mdi:bridge",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("modem_mode"), "bridge_mode", None),
    ),
    CompalBinaryDescription(
        key="wifi_2g",
        translation_key="wifi_2g",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_wifi_up("band2g"),
    ),
    CompalBinaryDescription(
        key="wifi_5g",
        translation_key="wifi_5g",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_wifi_up("band5g"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Compal binary sensors from a config entry."""
    coordinator: CompalDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities(
        CompalBinarySensor(coordinator, config_entry.entry_id, description)
        for description in BINARY_SENSORS
    )


class CompalBinarySensor(CompalEntity, BinarySensorEntity):
    """A single Compal gateway binary sensor."""

    entity_description: CompalBinaryDescription

    def __init__(
        self,
        coordinator: CompalDataUpdateCoordinator,
        entry_id: str,
        description: CompalBinaryDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        return self.entity_description.value_fn(self.coordinator.data or {})
