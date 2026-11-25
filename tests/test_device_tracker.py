"""MAC letter case in tracker unique IDs (issue #4)."""

from __future__ import annotations

from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
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


def _tracker(hass, entry, unique_id, object_id, **kwargs) -> er.RegistryEntry:
    """Create a tracker registry entry as an older release would have."""
    return er.async_get(hass).async_get_or_create(
        "device_tracker",
        DOMAIN,
        unique_id,
        config_entry=entry,
        suggested_object_id=object_id,
        **kwargs,
    )


async def test_duplicates_keep_the_customised_original(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """Validator scenario d: both enabled, the user customised the original.

    The original (upper-case ID, created first, renamed by the user) keeps its
    entity_id, name, area and device link. The lower-case copy is removed.
    """
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    living = ar.async_get(hass).async_create("Living room")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
    )
    original = _tracker(hass, config_entry, MAC_UPPER, "phone", device_id=device.id)
    copy = _tracker(hass, config_entry, MAC, "phone", device_id=device.id)
    assert copy.entity_id == "device_tracker.phone_2"
    # A rename moves the entry to the end of the registry, so registry order
    # alone would pick the copy.
    ent_reg.async_update_entity(
        original.entity_id,
        new_entity_id="device_tracker.my_phone",
        name="My phone",
        area_id=living.id,
        icon="mdi:cellphone",
        labels={"family"},
    )
    known_device(hass, MAC)
    mock_client.get_hosts.return_value = [make_host(MAC_UPPER), make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == "device_tracker.my_phone"
    assert tracker.unique_id == MAC
    assert tracker.name == "My phone"
    assert tracker.area_id == living.id
    assert tracker.icon == "mdi:cellphone"
    assert tracker.labels == {"family"}
    assert tracker.device_id == device.id
    assert ent_reg.async_get(copy.entity_id) is None
    assert hass.states.get("device_tracker.my_phone").state == STATE_HOME


async def test_duplicates_only_the_copy_is_customised(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """Both enabled, only the lower-case copy has user settings.

    The original keeps its entity_id and gets the settings it lacks.
    """
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    office = ar.async_get(hass).async_create("Office")
    original = _tracker(hass, config_entry, MAC_UPPER, "phone")
    ent_reg.async_update_entity(original.entity_id, labels={"family"})
    copy = _tracker(hass, config_entry, MAC, "phone")
    ent_reg.async_update_entity(
        copy.entity_id, name="Phone copy", area_id=office.id, labels={"guest"}
    )
    mock_client.get_hosts.return_value = [make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == original.entity_id == "device_tracker.phone"
    assert tracker.unique_id == MAC
    assert tracker.name == "Phone copy"
    assert tracker.area_id == office.id
    assert tracker.labels == {"family", "guest"}
    assert ent_reg.async_get(copy.entity_id) is None


async def test_duplicates_original_disabled_by_user(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """The user disabled the original and uses the copy.

    A disabled entity has no state, so the enabled copy stays with its
    entity_id and name. It gets the original's area, which it lacks.
    """
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    living = ar.async_get(hass).async_create("Living room")
    original = _tracker(hass, config_entry, MAC_UPPER, "tv")
    ent_reg.async_update_entity(
        original.entity_id,
        name="TV",
        area_id=living.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    copy = _tracker(hass, config_entry, MAC, "tv")
    ent_reg.async_update_entity(copy.entity_id, name="TV lower-case copy")
    known_device(hass, MAC)
    mock_client.get_hosts.return_value = [make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == copy.entity_id == "device_tracker.tv_2"
    assert tracker.unique_id == MAC
    assert tracker.disabled_by is None
    assert tracker.name == "TV lower-case copy"
    assert tracker.area_id == living.id
    assert ent_reg.async_get(original.entity_id) is None
    assert hass.states.get("device_tracker.tv_2").state == STATE_HOME


async def test_duplicates_copy_disabled_by_user(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """The user disabled the copy: the original stays enabled, as it was."""
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    original = _tracker(hass, config_entry, MAC_UPPER, "phone")
    copy = _tracker(
        hass,
        config_entry,
        MAC,
        "phone",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    mock_client.get_hosts.return_value = [make_host(MAC_UPPER), make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == original.entity_id
    assert tracker.unique_id == MAC
    assert tracker.disabled_by is None
    assert ent_reg.async_get(copy.entity_id) is None


async def test_duplicates_copy_device_has_a_user_area(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """The copy is in an area only through its device.

    The original has no area in any way, so it gets that area. Its device link
    stays. Home Assistant 2026.10 refuses an area of its own on a device-linked
    entity without a name of its own, so the area then goes on its device.
    """
    config_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    office = ar.async_get(hass).async_create("Office")
    own_device = dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
    )
    copy_device = dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "copy-device")},
    )
    dev_reg.async_update_device(copy_device.id, area_id=office.id)
    original = _tracker(
        hass, config_entry, MAC_UPPER, "phone", device_id=own_device.id
    )
    _tracker(hass, config_entry, MAC, "phone", device_id=copy_device.id)
    mock_client.get_hosts.return_value = [make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == original.entity_id
    assert tracker.device_id == own_device.id
    device_area = dev_reg.async_get(own_device.id).area_id
    assert (tracker.area_id or device_area) == office.id


async def test_duplicates_kept_entry_already_has_an_area(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """An area the kept entry has through its device is not overwritten."""
    config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    areas = ar.async_get(hass)
    living = areas.async_create("Living room")
    office = areas.async_create("Office")
    own_device = dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
    )
    dev_reg.async_update_device(own_device.id, area_id=living.id)
    original = _tracker(
        hass, config_entry, MAC_UPPER, "phone", device_id=own_device.id
    )
    copy = _tracker(hass, config_entry, MAC, "phone")
    ent_reg.async_update_entity(copy.entity_id, area_id=office.id)
    mock_client.get_hosts.return_value = [make_host(MAC)]

    await setup_entry(hass, config_entry)

    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.entity_id == original.entity_id
    assert tracker.area_id is None
    assert dev_reg.async_get(own_device.id).area_id == living.id
