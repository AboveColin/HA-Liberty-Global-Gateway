"""Fixtures: a config entry and a fake gateway client."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from liberty_global_gateway.exceptions import GatewayAPIError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.liberty_global_gateway.const import (
    CONF_HOST,
    CONF_PASSWORD,
    DOMAIN,
)

# Reads the coordinator wraps in _safe(). The fake client fails them all, which
# is what a firmware without those endpoints does, so the payload falls back to
# the defaults and the tests depend only on the reads they set.
OPTIONAL_READS = (
    "get_localization",
    "get_lan_info",
    "get_ipv6_info",
    "get_wifi_configs",
    "get_registration",
    "get_event_log",
    "get_provisioning",
    "get_software_update",
    "get_upnp",
    "get_dmz",
    "get_firewall",
    "get_smart_wifi",
    "get_guest_wifi_configs",
    "get_port_forwarding",
    "get_reserved_ips",
    "get_mta_lines",
    "get_led",
    "get_dhcp",
    "get_wps_enabled",
    "get_mac_filters",
    "get_port_triggers",
    "get_ip_port_filters",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


def make_host(mac: str, *, connected: bool = True, name: str = "client"):
    """Return a host record with the fields the integration reads."""
    return SimpleNamespace(
        mac_address=mac,
        connected=connected,
        name=name,
        hostname=name,
        ip_address="192.168.178.20" if connected else None,
        interface="wifi",
        device_type=None,
        band="5g",
        ssid="home",
        rssi=-50,
        speed=866,
        ethernet_port=None,
        ipv6_address=None,
        lease_time_remaining=3600,
    )


def make_client() -> MagicMock:
    """Return a fake LibertyGatewayClient with healthy DOCSIS reads."""
    client = MagicMock()
    client.login = AsyncMock()
    client.logout = AsyncMock()
    client.close = AsyncMock()
    client.get_system_info = AsyncMock(
        return_value=SimpleNamespace(
            model_name="F3896LG",
            software_version="1.0",
            hardware_version="1",
        )
    )
    client.get_modem_mode = AsyncMock(
        return_value=SimpleNamespace(bridge_mode=False)
    )
    client.get_cable_modem_state = AsyncMock(
        return_value=SimpleNamespace(
            operational=True,
            docsis_version="3.1",
            service_status="online",
            status="OPERATIONAL",
            uptime=3600,
            serial_number="SN1",
            baseline_privacy_enabled=True,
        )
    )
    client.get_downstream_channels = AsyncMock(
        return_value=[
            SimpleNamespace(
                channel_type="sc_qam",
                power=3.5,
                snr=40.0,
                corrected_errors=1,
                uncorrected_errors=0,
                lock_status=True,
            )
        ]
    )
    client.get_upstream_channels = AsyncMock(
        return_value=[
            SimpleNamespace(
                channel_type="atdma",
                power=42.0,
                t3_timeout=0,
                t4_timeout=0,
                lock_status=True,
            )
        ]
    )
    client.get_service_flows = AsyncMock(return_value=[])
    client.get_wifi_states = AsyncMock(return_value={})
    client.get_hosts = AsyncMock(return_value=[make_host("aa:bb:cc:dd:ee:01")])
    for name in OPTIONAL_READS:
        setattr(client, name, AsyncMock(side_effect=GatewayAPIError("not here")))
    return client


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the client class the integration builds in async_setup_entry."""
    client = make_client()
    with patch(
        "custom_components.liberty_global_gateway.LibertyGatewayClient",
        return_value=client,
    ):
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for a gateway, with no options set."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Ziggo SmartWifi modem (F3896LG)",
        data={CONF_HOST: "192.168.178.1", CONF_PASSWORD: "secret"},
        unique_id="192.168.178.1",
    )
