"""A failing /network/hosts read must not take the DOCSIS data down (issue #4)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from liberty_global_gateway.exceptions import (
    GatewayNetworkError,
    GatewaySessionBusyError,
)

from .conftest import make_host
from .helpers import known_device, refresh, sensor_state, setup_entry, tracker_entries

MAC = "aa:bb:cc:dd:ee:01"
TIMEOUT = GatewayNetworkError("request to /network/hosts timed out")


async def test_hosts_timeout_on_first_refresh_still_sets_up(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """A hosts timeout on the first poll loads the entry with the DOCSIS data."""
    mock_client.get_hosts.side_effect = TIMEOUT

    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert sensor_state(hass, config_entry, "docsis_status").state == "OPERATIONAL"
    assert sensor_state(hass, config_entry, "downstream_power_min").state == "3.5"
    # No client list was ever read, so the count is unknown, not 0.
    assert sensor_state(hass, config_entry, "connected_devices").state == STATE_UNKNOWN
    assert tracker_entries(hass, config_entry) == []


async def test_hosts_failures_keep_docsis_available(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """Repeated hosts failures make the trackers unavailable, not the sensors."""
    known_device(hass, MAC)
    mock_client.get_hosts.return_value = [make_host(MAC)]
    await setup_entry(hass, config_entry)
    (tracker,) = tracker_entries(hass, config_entry)
    assert hass.states.get(tracker.entity_id).state == STATE_HOME
    assert sensor_state(hass, config_entry, "connected_devices").state == "1"

    mock_client.get_hosts.side_effect = TIMEOUT
    # The first two failures replay the previous list.
    for _ in range(2):
        await refresh(hass, config_entry)
        assert hass.states.get(tracker.entity_id).state == STATE_HOME
        assert sensor_state(hass, config_entry, "connected_devices").state == "1"

    # The third one marks the list as too old to show.
    await refresh(hass, config_entry)
    assert hass.states.get(tracker.entity_id).state == STATE_UNAVAILABLE
    assert sensor_state(hass, config_entry, "connected_devices").state == STATE_UNKNOWN
    assert sensor_state(hass, config_entry, "docsis_status").state == "OPERATIONAL"
    assert sensor_state(hass, config_entry, "downstream_power_min").state == "3.5"

    # One good read brings the client list back.
    mock_client.get_hosts.side_effect = None
    await refresh(hass, config_entry)
    assert hass.states.get(tracker.entity_id).state == STATE_HOME
    assert sensor_state(hass, config_entry, "connected_devices").state == "1"


async def test_hosts_read_is_last_in_the_burst(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """The slow hosts read runs after every other read of the poll.

    A hosts timeout then costs no other read its data, even when the gateway
    stays busy with the client table for a while after the timeout.
    """
    await setup_entry(hass, config_entry)

    reads = [
        name
        for name, _args, _kwargs in mock_client.mock_calls
        if name.startswith("get_")
    ]
    assert reads[-1] == "get_hosts"
    assert reads.count("get_hosts") == 1


async def test_session_busy_during_hosts_is_not_swallowed(
    hass: HomeAssistant, config_entry, mock_client
) -> None:
    """A busy session slot is a whole-poll failure, as before."""
    mock_client.get_hosts.side_effect = GatewaySessionBusyError("busy")

    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
