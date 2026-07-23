"""Device tracker platform for the Compal / Sagemcom F3896LG integration.

Every host in the gateway's DHCP/association table becomes a router-source
``device_tracker`` entity, so presence detection follows devices joining and
leaving the network.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CompalDataUpdateCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device trackers, adding new ones as hosts appear."""
    coordinator: CompalDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    tracked: set[str] = set()

    @callback
    def _add_new_hosts() -> None:
        new_entities = []
        for host in (coordinator.data or {}).get("hosts") or []:
            mac = host.mac_address
            if not mac or mac in tracked:
                continue
            tracked.add(mac)
            new_entities.append(
                CompalDeviceTracker(coordinator, config_entry.entry_id, mac)
            )
        if new_entities:
            async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_add_new_hosts))
    _add_new_hosts()


class CompalDeviceTracker(
    CoordinatorEntity[CompalDataUpdateCoordinator], ScannerEntity
):
    """Presence for a single host seen by the gateway."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: CompalDataUpdateCoordinator, entry_id: str, mac: str
    ) -> None:
        """Initialize the tracker for one MAC address."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._mac = mac
        self._attr_unique_id = f"{entry_id}_{mac}"

    @property
    def _host(self):
        """Return the current host record for this MAC, if present."""
        for host in (self.coordinator.data or {}).get("hosts") or []:
            if host.mac_address == self._mac:
                return host
        return None

    @property
    def name(self) -> str | None:
        """Return the friendly device name."""
        host = self._host
        return host.name if host else self._mac

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        """Return whether the device is currently connected."""
        host = self._host
        return bool(host and host.connected)

    @property
    def ip_address(self) -> str | None:
        """Return the device's IPv4 address."""
        host = self._host
        return host.ip_address if host else None

    @property
    def mac_address(self) -> str:
        """Return the device's MAC address."""
        return self._mac

    @property
    def hostname(self) -> str | None:
        """Return the device's hostname."""
        host = self._host
        return host.hostname if host else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return interface details for the tracked device."""
        host = self._host
        if host is None:
            return {}
        return {
            "interface": host.interface,
            "band": host.band,
            "ssid": host.ssid,
            "ethernet_port": host.ethernet_port,
        }
