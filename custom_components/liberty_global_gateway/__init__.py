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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

try:
    from liberty_global_gateway import LibertyGatewayClient
    from liberty_global_gateway.exceptions import (
        GatewayAuthError,
        GatewayError,
        GatewayLockoutError,
        GatewaySessionBusyError,
    )
except ImportError as err:  # pragma: no cover - handled by manifest requirements
    _LOGGER.error("Failed to import the liberty_global_gateway package: %s", err)
    raise

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_TRACK_CLIENTS,
    DEFAULT_TRACK_CLIENTS,
    DOMAIN,
)

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

    def __init__(
        self,
        hass: HomeAssistant,
        client: LibertyGatewayClient,
        track_clients: bool = DEFAULT_TRACK_CLIENTS,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        # With client tracking off, /network/hosts is never requested.
        self.track_clients = track_clients
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
                # Last in the burst: it is the slowest read and may run into its
                # 60 s timeout, and by then everything else is already in hand.
                hosts, hosts_available = await self._read_hosts()
        except GatewayLockoutError as err:
            # A lockout is a few-minute cooldown that clears by itself, and the
            # stored password is still correct. Raising ConfigEntryAuthFailed here
            # would tell the user their credentials are wrong when they are not.
            # This clause must come before GatewayAuthError: the lockout error
            # is a subclass of it, so the auth clause would catch it first.
            raise UpdateFailed(
                f"Gateway is locked out, retrying after the cooldown: {err}"
            ) from err
        except GatewayAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
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
            "hosts_available": hosts_available,
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

    async def _read_hosts(self) -> tuple[list, bool]:
        """Read the client table, never failing the poll because of it.

        Returns the host list and whether it is current enough to show. The
        DOCSIS data does not depend on /network/hosts, and on a busy LAN that
        endpoint can take longer than its 60 s timeout. A failure here keeps the
        previous list (or an empty one on the first poll) and the rest of the
        payload is still published.

        The replay of a previous list is bounded like the session-busy replay:
        after MAX_STALE_CYCLES failed reads in a row the list is marked as not
        available, so the trackers go unavailable and the connected-devices
        count goes unknown instead of showing presence from 15 minutes ago.
        """
        if not self.track_clients:
            return [], False
        prev_hosts = (self.data or {}).get("hosts")
        try:
            hosts = await self.client.get_hosts(connected_only=False)
        except (GatewayAuthError, GatewaySessionBusyError):
            # The session itself is gone, not just this endpoint. The outer
            # handlers deal with that for the whole payload.
            raise
        except GatewayError as err:
            self._stale_host_cycles += 1
            available = (
                prev_hosts is not None
                and self._stale_host_cycles <= MAX_STALE_CYCLES
            )
            # Warn once per run of failures; a gateway that is slow every poll
            # would otherwise write a warning every five minutes.
            log = _LOGGER.warning if self._stale_host_cycles == 1 else _LOGGER.debug
            log(
                "Reading the client list failed (%s in a row), %s: %s",
                self._stale_host_cycles,
                "keeping the previous list" if available
                else "client trackers are unavailable until it succeeds",
                err,
            )
            return list(prev_hosts or []), available
        if self._stale_host_cycles:
            _LOGGER.info(
                "Client list read again after %s failed polls", self._stale_host_cycles
            )
        self._stale_host_cycles = 0
        return hosts, True

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


def _track_clients(entry: ConfigEntry) -> bool:
    """Return whether this entry tracks the gateway's clients."""
    return entry.options.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS)


def _platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the platforms to load; device_tracker only with client tracking."""
    if _track_clients(entry):
        return PLATFORMS
    return [p for p in PLATFORMS if p is not Platform.DEVICE_TRACKER]


@callback
def _async_migrate_tracker_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rewrite tracker unique IDs to the lower-case MAC form of format_mac().

    Before 2.1.0 the unique ID was the MAC exactly as the gateway sent it, and
    the gateway does not always send the same letter case. One client could so
    end up with two tracker entities. Every tracker entry is mapped to
    format_mac(unique_id), and the new unique ID can belong to one entry only.

    Rule for one MAC with more than one entry: keep the entry that has a state
    (an enabled entry before a disabled one, and among those the oldest), copy
    to it each user setting it does not have from the entries that are removed,
    then give it the new unique ID.

    - A disabled entry has no state, so nothing can rely on it; an enabled
      entry can be in automations and dashboards.
    - Among enabled entries the oldest is the original the user set up. A copy
      that the gateway's case change created later is not.
    - The kept entry's entity_id, device link, enabled and hidden state stay
      as they are. Its name, icon and area are filled in from a removed entry
      only where the kept entry has none, and labels are merged. An area that
      a removed entry had, on the entity or through its device, goes to the
      kept entry only if that entry has no area in any way.
    """
    ent_reg = er.async_get(hass)
    groups: dict[str, list[er.RegistryEntry]] = {}
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain != Platform.DEVICE_TRACKER:
            continue
        groups.setdefault(format_mac(reg_entry.unique_id), []).append(reg_entry)

    for new_id, reg_entries in groups.items():
        if len(reg_entries) == 1 and reg_entries[0].unique_id == new_id:
            continue
        # Registry order breaks a tie in created_at. Entries from before Home
        # Assistant recorded created_at all carry the same epoch value.
        order = {e.entity_id: i for i, e in enumerate(reg_entries)}
        keep, *duplicates = sorted(
            reg_entries,
            key=lambda e: (e.disabled_by is not None, e.created_at, order[e.entity_id]),
        )
        changes = _settings_to_keep(hass, keep, duplicates)
        for duplicate in duplicates:
            _LOGGER.info(
                "Removing %s: it tracks the same MAC as %s",
                duplicate.entity_id,
                keep.entity_id,
            )
            ent_reg.async_remove(duplicate.entity_id)
        if keep.unique_id != new_id:
            _LOGGER.debug(
                "Migrating the unique ID of %s from %s to %s",
                keep.entity_id,
                keep.unique_id,
                new_id,
            )
            ent_reg.async_update_entity(keep.entity_id, new_unique_id=new_id)
        _async_apply_settings(hass, keep.entity_id, changes)


@callback
def _async_apply_settings(
    hass: HomeAssistant, entity_id: str, changes: dict[str, Any]
) -> None:
    """Write the settings taken over from removed duplicates.

    Since Home Assistant 2026.10 an entity that is linked to a device and has
    no name of its own cannot have an area of its own; the registry raises
    ValueError. The area then goes on the device, which has no area (the keep
    rule only moves an area when the kept entry has none). A setting that the
    registry still refuses is logged and skipped, so the migration never
    stops the entry from loading.
    """
    ent_reg = er.async_get(hass)
    area_id = changes.pop("area_id", None)
    if changes:
        try:
            ent_reg.async_update_entity(entity_id, **changes)
        except ValueError as err:
            _LOGGER.warning("Could not copy %s to %s: %s", changes, entity_id, err)
    if area_id is None:
        return
    try:
        ent_reg.async_update_entity(entity_id, area_id=area_id)
    except ValueError:
        reg_entry = ent_reg.async_get(entity_id)
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(reg_entry.device_id) if reg_entry else None
        if device is not None and device.area_id is None:
            dev_reg.async_update_device(device.id, area_id=area_id)


def _settings_to_keep(
    hass: HomeAssistant,
    keep: er.RegistryEntry,
    duplicates: list[er.RegistryEntry],
) -> dict[str, Any]:
    """Return the user settings of the duplicates that the kept entry lacks.

    The duplicates come in the order of the keep rule, so where two of them
    have a name, the one that ranks higher gives it.
    """
    dev_reg = dr.async_get(hass)

    def device_area(reg_entry: er.RegistryEntry) -> str | None:
        device = dev_reg.async_get(reg_entry.device_id) if reg_entry.device_id else None
        return device.area_id if device else None

    changes: dict[str, Any] = {}
    name, icon = keep.name, keep.icon
    has_area = keep.area_id is not None or device_area(keep) is not None
    area_id = None
    labels = set(keep.labels)
    for duplicate in duplicates:
        name = name or duplicate.name
        icon = icon or duplicate.icon
        if not has_area and area_id is None:
            area_id = duplicate.area_id or device_area(duplicate)
        labels |= duplicate.labels
    if name != keep.name:
        changes["name"] = name
    if icon != keep.icon:
        changes["icon"] = icon
    if area_id is not None:
        changes["area_id"] = area_id
    if labels != keep.labels:
        changes["labels"] = labels
    return changes


@callback
def _async_remove_client_tracking(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the tracker entities and client devices of this entry.

    Runs when client tracking is off. Without this, the tracker entities stay
    in the entity registry as "no longer provided" and the client devices stay
    on the device page of this integration. The gateway device stays.
    """
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == Platform.DEVICE_TRACKER:
            ent_reg.async_remove(reg_entry.entity_id)

    dev_reg = dr.async_get(hass)
    gateway = (DOMAIN, entry.entry_id)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if gateway in device.identifiers:
            continue
        if getattr(device, "config_entry_id", None) is not None:
            # Newer Home Assistant releases give every device one config entry
            # (2026.10 does, 2026.2 does not). A tracker then registers its own
            # device even when another integration knows the MAC, and that
            # device is this entry's alone.
            dev_reg.async_remove_device(device.id)
        else:
            # Older releases add this entry to the device of the integration
            # that knows the MAC. Take only this entry off; Home Assistant
            # deletes the device when no config entry uses it any more.
            # Remove this branch when hacs.json requires a release with one
            # config entry per device.
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Liberty Global cable gateway from a config entry."""
    track_clients = _track_clients(entry)
    if track_clients:
        _async_migrate_tracker_unique_ids(hass, entry)
    else:
        _async_remove_client_tracking(hass, entry)

    session = async_get_clientsession(hass)
    client = LibertyGatewayClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PASSWORD],
        session=session,
    )

    coordinator = GatewayDataUpdateCoordinator(hass, client, track_clients)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err

    platforms = _platforms(entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        # Unload must undo exactly what was set up. The options may already
        # have changed by then, so the list is not derived from them again.
        "platforms": platforms,
    }

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when the client-tracking option changed.

    The listener also fires for other entry updates, such as the new password
    of a re-authentication, which reloads the entry by itself.
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    if coordinator.track_clients != _track_clients(entry):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = hass.data[DOMAIN][entry.entry_id]["platforms"]
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, platforms):
        domain_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if domain_data:
            await domain_data["client"].close()
    return unload_ok
