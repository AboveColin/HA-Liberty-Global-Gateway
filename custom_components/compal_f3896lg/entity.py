"""Base entity for the Compal / Sagemcom F3896LG integration."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CompalDataUpdateCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL


class CompalEntity(CoordinatorEntity[CompalDataUpdateCoordinator]):
    """Base entity tying platform entities to the gateway device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CompalDataUpdateCoordinator, entry_id: str, key: str
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
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Ziggo Cable Gateway",
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
