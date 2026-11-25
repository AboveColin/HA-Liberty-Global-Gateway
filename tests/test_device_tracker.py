"""MAC letter case in tracker unique IDs (issue #4)."""

from __future__ import annotations

from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.liberty_global_gateway.const import DOMAIN

from .conftest import make_host
from .helpers import known_device, sensor_state, setup_entry, tracker_entries

MAC = "aa:bb:cc:dd:ee:01"
MAC_UPPER = "AA:BB:CC:DD:EE:01"


async def test_case_variants_make_one_tracker(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """One MAC in two letter cases is one tracker, and counts once."""
    known_device(hass, MAC)
    mock_client.get_hosts.return_value = [
        make_host(MAC_UPPER, connected=False, name="old record"),
        make_host(MAC, connected=True, name="Phone"),
    ]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.unique_id == MAC
    # The connected record wins over the old one.
    assert hass.states.get(tracker.entity_id).state == STATE_HOME
    assert sensor_state(hass, config_entry, "connected_devices").state == "1"


async def test_upper_case_unique_id_is_migrated(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """An entity from before 2.1.0 keeps its entity_id and gets the new ID."""
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "device_tracker",
        DOMAIN,
        MAC_UPPER,
        config_entry=config_entry,
        suggested_object_id="phone",
    )
    mock_client.get_hosts.return_value = [make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == old.entity_id == "device_tracker.phone"
    assert tracker.unique_id == MAC


async def test_duplicate_entries_are_merged(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """Two existing entries for one MAC become one; the enabled one stays."""
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    enabled = ent_reg.async_get_or_create(
        "device_tracker",
        DOMAIN,
        MAC_UPPER,
        config_entry=config_entry,
        suggested_object_id="phone",
    )
    disabled = ent_reg.async_get_or_create(
        "device_tracker",
        DOMAIN,
        MAC,
        config_entry=config_entry,
        suggested_object_id="phone_2",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    mock_client.get_hosts.return_value = [make_host(MAC_UPPER), make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == enabled.entity_id
    assert tracker.unique_id == MAC
    assert ent_reg.async_get(disabled.entity_id) is None
