"""The Liberty Global cable gateway integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

try:
    from liberty_global_gateway import LibertyGatewayClient
    from liberty_global_gateway.exceptions import (
        GatewayAuthError,
        GatewayError,
        GatewayLockoutError,
        GatewayNetworkError,
        GatewaySessionBusyError,
    )
except ImportError as err:  # pragma: no cover - handled by manifest requirements
    _LOGGER.error("Failed to import the liberty_global_gateway package: %s", err)
    raise

from .const import CONF_HOST, CONF_PASSWORD, DOMAIN

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
    Platform.NUMBER,
]

# The gateway allows a single session and frees the slot only after the token
# idles out (~15 min). We log in, read a burst and drop the token every cycle,
# so the router's web UI stays usable between polls. Successful logins never
# count toward the lockout, so a 5-minute cadence is safe.
SCAN_INTERVAL = timedelta(minutes=5)

# How many consecutive polls may serve the previous payload when the gateway's
# single session is held elsewhere. Two cycles is 10 minutes of replay, past
# which the entry goes unavailable rather than showing stale values as current.
MAX_STALE_CYCLES = 2


class GatewayDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator that logs in, reads a burst and drops the token each cycle."""

    def __init__(self, hass: HomeAssistant, client: LibertyGatewayClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        # The gateway allows exactly one authenticated session, and a second
        # login revokes the first token. Serialise every login-to-logout span,
        # or a button press during a poll breaks both halves.
        self._session_lock = asyncio.Lock()
        self._stale_cycles = 0
        self._stale_host_cycles = 0
        self._boot_time: datetime | None = None
        # Operator branding (skin + product name). Static for the life of a
        # firmware, so it is read once and reused for the device registry name.
        self.localization = None

    def _stable_boot_time(self, cable: Any) -> datetime | None:
        """Derive a boot timestamp from uptime, held steady between reboots.

        utcnow() minus uptime lands a second or so away on every poll, which
        would rewrite the timestamp sensor every five minutes and churn recorder
        history. Keep the first value and only move it when the two disagree by
        more than a minute, which is what an actual reboot looks like.
        """
        uptime = getattr(cable, "uptime", None)
        if uptime is None:
            return self._boot_time
        boot = dt_util.utcnow().replace(microsecond=0) - timedelta(seconds=int(uptime))
        if (
            self._boot_time is None
            or abs((boot - self._boot_time).total_seconds()) > 60
        ):
            self._boot_time = boot
        return self._boot_time

    @asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        """Hold the gateway's single session slot for one login-to-logout span.

        Logging out releases the slot at once (DELETE /user/<id>/token/<token>)
        instead of waiting for the ~15 minute idle timeout, so the router's web
        UI stays usable between polls. Best effort inside the library.
        """
        async with self._session_lock:
            await self.client.login()
            try:
                yield
            finally:
                await self.client.logout()

    async def _async_update_data(self) -> dict:
        """Log in, read the gateway in one burst, then release the session slot."""
        try:
            async with self.session():

                if self.localization is None:
                    self.localization = await self._safe(self.client.get_localization())

                system = await self.client.get_system_info()
                modem_mode = await self.client.get_modem_mode()
                cable = await self.client.get_cable_modem_state()
                downstream = await self.client.get_downstream_channels()
                upstream = await self.client.get_upstream_channels()
                service_flows = await self.client.get_service_flows()
                wifi_states = await self.client.get_wifi_states()
                try:
                    hosts = await self.client.get_hosts(connected_only=False)
                except GatewayNetworkError as err:
                    # The hosts table is the slowest endpoint; if it blips, keep the
                    # previous list rather than dropping every device_tracker. Bounded
                    # like the session-busy replay above, because a host list that
                    # lags the rest of the payload makes presence quietly wrong.
                    prev_hosts = (self.data or {}).get("hosts")
                    if prev_hosts is None or self._stale_host_cycles >= MAX_STALE_CYCLES:
                        raise
                    self._stale_host_cycles += 1
                    _LOGGER.debug(
                        "hosts read failed (%s); replaying previous list (%s/%s)",
                        err,
                        self._stale_host_cycles,
                        MAX_STALE_CYCLES,
                    )
                    hosts = prev_hosts
                else:
                    self._stale_host_cycles = 0
                # Supplementary reads — best effort, so firmware that lacks any of
                # them never breaks the whole poll.
                lan = await self._safe(self.client.get_lan_info())
                ipv6 = await self._safe(self.client.get_ipv6_info())
                wifi_configs = await self._safe(
                    self.client.get_wifi_configs(), default={}
                )
                registration = await self._safe(self.client.get_registration())
                event_log = await self._safe(self.client.get_event_log(), default=[])
                provisioning = await self._safe(self.client.get_provisioning())
                software_update = await self._safe(self.client.get_software_update())
                upnp = await self._safe(self.client.get_upnp())
                dmz = await self._safe(self.client.get_dmz())
                firewall = await self._safe(self.client.get_firewall("ipv4"))
                smart_wifi = await self._safe(self.client.get_smart_wifi())
                guest_wifi = await self._safe(
                    self.client.get_guest_wifi_configs(), default={})
                port_forwarding = await self._safe(
                    self.client.get_port_forwarding(), default=[])
                reserved_ips = await self._safe(
                    self.client.get_reserved_ips(), default=[])
                mta_lines = await self._safe(self.client.get_mta_lines(), default=[])
                led = await self._safe(self.client.get_led())
                dhcp = await self._safe(self.client.get_dhcp("ipv4"))
                wps = {
                    "band2g": await self._safe(self.client.get_wps_enabled("band2g")),
                    "band5g": await self._safe(self.client.get_wps_enabled("band5g")),
                }
                mac_filters = await self._safe(self.client.get_mac_filters(), default=[])
                port_triggers = await self._safe(
                    self.client.get_port_triggers(), default=[])
                ip_port_filters = await self._safe(
                    self.client.get_ip_port_filters(), default=[])
        except GatewayAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayLockoutError as err:
            # A lockout is a few-minute cooldown that clears by itself, and the
            # stored password is still correct. Raising ConfigEntryAuthFailed here
            # would tell the user their credentials are wrong when they are not.
            raise UpdateFailed(
                f"Gateway is locked out, retrying after the cooldown: {err}"
            ) from err
        except GatewaySessionBusyError as err:
            # The web UI (or a prior client) holds the single session. Replay the
            # last-known values for a couple of cycles rather than flapping every
            # entity to unavailable, then give up: an unbounded replay serves
            # arbitrarily old data while the entry still reports as healthy.
            if self.data is not None and self._stale_cycles < MAX_STALE_CYCLES:
                self._stale_cycles += 1
                _LOGGER.debug(
                    "Gateway session busy; replaying previous data (%s/%s): %s",
                    self._stale_cycles,
                    MAX_STALE_CYCLES,
                    err,
                )
                return self.data
            raise UpdateFailed(
                "Gateway session is busy (close the router web UI)"
            ) from err
        except GatewayError as err:
            raise UpdateFailed(f"Error communicating with the gateway: {err}") from err

        self._stale_cycles = 0
        return {
            "system": system,
            "modem_mode": modem_mode,
            "cable": cable,
            "boot_time": self._stable_boot_time(cable),
            "downstream": downstream,
            "upstream": upstream,
            "service_flows": service_flows,
            "wifi_states": wifi_states,
            "wifi_configs": wifi_configs or {},
            "hosts": hosts,
            "lan": lan,
            "ipv6": ipv6,
            "registration": registration,
            "event_log": event_log or [],
            "provisioning": provisioning,
            "software_update": software_update,
            "upnp": upnp,
            "dmz": dmz,
            "firewall": firewall,
            "smart_wifi": smart_wifi,
            "guest_wifi": guest_wifi or {},
            "port_forwarding": port_forwarding or [],
            "reserved_ips": reserved_ips or [],
            "mta_lines": mta_lines or [],
            "led": led,
            "dhcp": dhcp,
            "wps": wps,
            "mac_filters": mac_filters or [],
            "port_triggers": port_triggers or [],
            "ip_port_filters": ip_port_filters or [],
            "signal": _signal_stats(downstream, upstream),
            "plan": _plan_rates(service_flows),
        }

    async def _safe(self, coro, default=None):
        """Await an optional read, returning ``default`` if the endpoint fails."""
        try:
            return await coro
        except GatewayError as err:
            _LOGGER.debug("optional gateway read failed: %s", err)
            return default


def _is_sc_qam(channel) -> bool:
    """Return True for SC-QAM downstream channels (not OFDM)."""
    channel_type = (channel.channel_type or "").lower()
    if channel_type:
        return channel_type == "sc_qam"
    # Fall back to the SNR signal: SC-QAM channels report SNR, OFDM ones don't.
    return channel.snr is not None


def _signal_stats(downstream: list, upstream: list) -> dict:
    """Aggregate per-channel DOCSIS figures into a few headline numbers."""
    # OFDM (DOCSIS 3.1) channels report received power on a different scale than
    # the SC-QAM channels — often well over 100 "dBmV" — and expose no SNR, so
    # the headline power/SNR figures cover the SC-QAM channels only to stay in a
    # comparable, meaningful dBmV range.
    qam = [c for c in downstream if _is_sc_qam(c)]
    powers = [c.power for c in qam if c.power is not None]
    snrs = [c.snr for c in qam if c.snr is not None]
    corrected = sum(c.corrected_errors or 0 for c in downstream)
    uncorrected = sum(c.uncorrected_errors or 0 for c in downstream)
    # Upstream: OFDMA channels report power on a different scale than the SC-QAM
    # (ATDMA) channels (observed ~330 vs ~40), so restrict to non-OFDMA here.
    up_powers = [
        c.power for c in upstream
        if c.power is not None and "ofdma" not in (c.channel_type or "").lower()
    ]
    return {
        "downstream_channels": len(downstream),
        "upstream_channels": len(upstream),
        "downstream_power_min": min(powers) if powers else None,
        "downstream_power_max": max(powers) if powers else None,
        "downstream_snr_min": min(snrs) if snrs else None,
        "upstream_power_min": min(up_powers) if up_powers else None,
        "upstream_power_max": max(up_powers) if up_powers else None,
        "corrected_errors": corrected,
        "uncorrected_errors": uncorrected,
        # Line-health counters: T3/T4 timeouts and how many channels are locked.
        "t3_timeouts": sum(c.t3_timeout or 0 for c in upstream),
        "t4_timeouts": sum(c.t4_timeout or 0 for c in upstream),
        "downstream_locked": sum(1 for c in downstream if c.lock_status),
        "upstream_locked": sum(1 for c in upstream if c.lock_status),
    }


def _plan_rates(service_flows: list) -> dict:
    """Pull the provisioned down/up rate caps (Mbps) out of the service flows."""
    down = None
    up = None
    for flow in service_flows:
        rate = flow.max_traffic_rate_mbps
        if rate is None:
            continue
        direction = (flow.direction or "").lower()
        is_down = direction.startswith("down") or direction == "ds"
        is_up = direction.startswith("up") or direction == "us"
        if is_down and (down is None or rate > down):
            down = rate
        elif is_up and (up is None or rate > up):
            up = rate
    return {"download_mbps": down, "upload_mbps": up}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Liberty Global cable gateway from a config entry."""
    session = async_get_clientsession(hass)
    client = LibertyGatewayClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PASSWORD],
        session=session,
    )

    coordinator = GatewayDataUpdateCoordinator(hass, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        domain_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if domain_data:
            await domain_data["client"].close()
    return unload_ok
