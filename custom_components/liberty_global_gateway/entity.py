"""Base entity for the Liberty Global cable gateway integration."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GatewayDataUpdateCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL


class GatewayEntity(CoordinatorEntity[GatewayDataUpdateCoordinator]):
    """Base entity tying platform entities to the gateway device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GatewayDataUpdateCoordinator, entry_id: str, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._key = key
        self._attr_unique_id = f"{entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the gateway device that all entities hang off."""
        data = self.coordinator.data or {}
        system = data.get("system")
        cable = data.get("cable")
        # Prefer the operator's own product branding ("Ziggo SmartWifi modem
        # (F3896LG)") over a generic label; fall back for firmware that does not
        # expose the localization endpoint.
        localization = getattr(self.coordinator, "localization", None)
        name = getattr(localization, "display_name", None) or "Cable Gateway"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=name,
            manufacturer=MANUFACTURER,
            model=getattr(system, "model_name", None) or MODEL,
            sw_version=getattr(system, "software_version", None),
            hw_version=getattr(system, "hardware_version", None),
            serial_number=getattr(cable, "serial_number", None),
        )

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return self.coordinator.last_update_success
