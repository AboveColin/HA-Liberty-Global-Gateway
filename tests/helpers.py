"""Shared helpers for the integration tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.liberty_global_gateway.const import DOMAIN


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry to hass, unless a test already did, and set it up."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def sensor_state(hass: HomeAssistant, entry: MockConfigEntry, key: str):
    """Return the state object of one gateway sensor."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None, f"no sensor for {key}"
    return hass.states.get(entity_id)


def tracker_entries(hass: HomeAssistant, entry: MockConfigEntry) -> list:
    """Return the device_tracker registry entries of the entry."""
    return [
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "device_tracker"
    ]


def known_device(hass: HomeAssistant, mac: str) -> dr.DeviceEntry:
    """Register a device with this MAC under another integration.

    Home Assistant enables a router tracker by default only when some other
    integration already knows the MAC, and only then links a device to it.
    """
    other = MockConfigEntry(domain="other_router")
    other.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, mac)},
        name="Phone",
    )


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run one coordinator poll and let the entities write their state."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
