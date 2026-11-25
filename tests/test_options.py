"""The "Track clients" option (issue #4)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.liberty_global_gateway.const import (
    CONF_HOST,
    CONF_PASSWORD,
    DOMAIN,
)

from .conftest import make_host
from .helpers import known_device, sensor_state, setup_entry, tracker_entries

MAC = "aa:bb:cc:dd:ee:01"
# The key is stored in entry.options, so it is spelled out here: renaming the
# constant must not silently change what existing entries have saved.
CONF_TRACK_CLIENTS = "track_clients"


def _entry_without_tracking() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "192.168.178.1", CONF_PASSWORD: "secret"},
        options={CONF_TRACK_CLIENTS: False},
        unique_id="192.168.178.1",
    )


async def test_tracking_is_on_by_default(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """An entry without options keeps reading hosts and adding trackers."""
    await setup_entry(hass, config_entry)

    mock_client.get_hosts.assert_awaited_once_with(connected_only=False)
    assert len(tracker_entries(hass, config_entry)) == 1
    assert sensor_state(hass, config_entry, "connected_devices").state == "1"


async def test_tracking_off_skips_hosts(hass: HomeAssistant, mock_client) -> None:
    """With the option off there is no hosts request and no tracker."""
    entry = _entry_without_tracking()

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    mock_client.get_hosts.assert_not_called()
    assert tracker_entries(hass, entry) == []
    assert hass.states.async_entity_ids("device_tracker") == []
    assert sensor_state(hass, entry, "connected_devices").state == STATE_UNKNOWN
    assert sensor_state(hass, entry, "docsis_status").state == "OPERATIONAL"
    # The device_tracker platform is not set up at all.
    assert "liberty_global_gateway.device_tracker" not in hass.config.components


async def test_options_flow(hass: HomeAssistant, config_entry, mock_client) -> None:
    """The options form shows the current value and saves the new one."""
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    (key,) = [k for k in schema if k == CONF_TRACK_CLIENTS]
    assert key.default() is True

    mock_client.get_hosts.reset_mock()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_TRACK_CLIENTS: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_TRACK_CLIENTS: False}
    # The entry reloaded with the new option, so the new poll skipped hosts.
    assert config_entry.state is ConfigEntryState.LOADED
    assert mock_client.login.await_count >= 2
    mock_client.get_hosts.assert_not_called()


async def test_turning_tracking_off_removes_trackers_and_client_devices(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """Turning the option off removes what client tracking created.

    The tracker entity goes, and the client device it is linked to goes or (on
    a release that shares devices between integrations) no longer lists this
    entry. The device another integration registered for the MAC stays, and so
    does the gateway device.
    """
    other = known_device(hass, MAC)
    mock_client.get_hosts.return_value = [make_host(MAC)]
    await setup_entry(hass, config_entry)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    (tracker,) = tracker_entries(hass, config_entry)
    client_device_id = tracker.device_id
    assert client_device_id is not None
    (gateway,) = [
        d
        for d in dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id)
        if (DOMAIN, config_entry.entry_id) in d.identifiers
    ]

    hass.config_entries.async_update_entry(
        config_entry, options={CONF_TRACK_CLIENTS: False}
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert tracker_entries(hass, config_entry) == []
    assert ent_reg.async_get(tracker.entity_id) is None
    assert [
        d.id
        for d in dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id)
    ] == [gateway.id]
    assert dev_reg.async_get(other.id) is not None
    if client_device_id != other.id:
        assert dev_reg.async_get(client_device_id) is None

    # Turning it back on brings the tracker back for the same MAC.
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_TRACK_CLIENTS: True}
    )
    await hass.async_block_till_done()
    (tracker,) = tracker_entries(hass, config_entry)
    assert tracker.unique_id == MAC
