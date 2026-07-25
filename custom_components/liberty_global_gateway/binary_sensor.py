"""Binary sensor platform for the Liberty Global cable gateway integration."""

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

from . import GatewayDataUpdateCoordinator
from .const import DOMAIN
from .entity import GatewayEntity


def _wifi_up(band: str) -> Callable[[dict], bool | None]:
    def _fn(data: dict) -> bool | None:
        state = (data.get("wifi_states") or {}).get(band)
        return None if state is None else state.up

    return _fn


@dataclass(frozen=True, kw_only=True)
class GatewayBinaryDescription(BinarySensorEntityDescription):
    """Describes a gateway binary sensor and how to read its state."""

    value_fn: Callable[[dict], bool | None]
    attr_fn: Callable[[dict], dict] | None = None


BINARY_SENSORS: tuple[GatewayBinaryDescription, ...] = (
    GatewayBinaryDescription(
        key="modem_operational",
        translation_key="modem_operational",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: getattr(d.get("cable"), "operational", None),
    ),
    GatewayBinaryDescription(
        key="bridge_mode",
        translation_key="bridge_mode",
        icon="mdi:bridge",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("modem_mode"), "bridge_mode", None),
    ),
    GatewayBinaryDescription(
        key="wifi_2g",
        translation_key="wifi_2g",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_wifi_up("band2g"),
    ),
    GatewayBinaryDescription(
        key="wifi_5g",
        translation_key="wifi_5g",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_wifi_up("band5g"),
    ),
    GatewayBinaryDescription(
        key="baseline_privacy",
        translation_key="baseline_privacy",
        icon="mdi:lock-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("cable"), "baseline_privacy_enabled", None),
    ),
    GatewayBinaryDescription(
        key="registration_complete",
        translation_key="registration_complete",
        icon="mdi:check-decagram",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("registration"), "registration_complete", None),
    ),
    GatewayBinaryDescription(
        key="downstream_locked",
        translation_key="downstream_locked",
        icon="mdi:lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("registration"), "downstream_locked", None),
    ),
    GatewayBinaryDescription(
        key="upnp",
        translation_key="upnp",
        icon="mdi:upload-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("upnp"),
    ),
    GatewayBinaryDescription(
        key="dmz",
        translation_key="dmz",
        device_class=BinarySensorDeviceClass.SAFETY,
        icon="mdi:security-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("dmz"), "enabled", None),
    ),
    GatewayBinaryDescription(
        key="firewall",
        translation_key="firewall",
        icon="mdi:shield-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("firewall"), "enabled", None),
    ),
    GatewayBinaryDescription(
        key="smart_wifi",
        translation_key="smart_wifi",
        icon="mdi:wifi-cog",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("smart_wifi"),
    ),
    GatewayBinaryDescription(
        key="guest_wifi_2g",
        translation_key="guest_wifi_2g",
        icon="mdi:wifi-lock-open",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr((d.get("guest_wifi") or {}).get("band2g"), "enabled", None),
        attr_fn=lambda d: {"ssid": getattr((d.get("guest_wifi") or {}).get("band2g"), "ssid", None)},
    ),
    GatewayBinaryDescription(
        key="guest_wifi_5g",
        translation_key="guest_wifi_5g",
        icon="mdi:wifi-lock-open",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr((d.get("guest_wifi") or {}).get("band5g"), "enabled", None),
        attr_fn=lambda d: {"ssid": getattr((d.get("guest_wifi") or {}).get("band5g"), "ssid", None)},
    ),
    GatewayBinaryDescription(
        key="wps_2g",
        translation_key="wps_2g",
        icon="mdi:wifi-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("wps") or {}).get("band2g"),
    ),
    GatewayBinaryDescription(
        key="wps_5g",
        translation_key="wps_5g",
        icon="mdi:wifi-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("wps") or {}).get("band5g"),
    ),
    GatewayBinaryDescription(
        key="dslite",
        translation_key="dslite",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("provisioning"), "dslite_enabled", None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the gateway binary sensors from a config entry."""
    coordinator: GatewayDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities(
        GatewayBinarySensor(coordinator, config_entry.entry_id, description)
        for description in BINARY_SENSORS
    )


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    """A single gateway binary sensor."""

    entity_description: GatewayBinaryDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        entry_id: str,
        description: GatewayBinaryDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes if the description defines them."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data or {})
