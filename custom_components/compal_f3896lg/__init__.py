"""The Compal F3896LG integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

try:
    from compalf3896lg import CompalClient
    from compalf3896lg.exceptions import (
        CompalAuthError,
        CompalError,
        CompalLockoutError,
        CompalSessionBusyError,
    )
except ImportError as err:  # pragma: no cover - handled by manifest requirements
    _LOGGER.error("Failed to import the compalf3896lg package: %s", err)
    raise

from .const import CONF_HOST, CONF_PASSWORD, DOMAIN

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
]

# The gateway allows a single session and frees the slot only after the token
# idles out (~15 min). We log in, read a burst and drop the token every cycle,
# so the router's web UI stays usable between polls. Successful logins never
# count toward the lockout, so a 5-minute cadence is safe.
SCAN_INTERVAL = timedelta(minutes=5)


class CompalDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator that logs in, reads a burst and drops the token each cycle."""

    def __init__(self, hass: HomeAssistant, client: CompalClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        """Log in, read the gateway in one burst, then release the session slot."""
        try:
            await self.client.login()

            system = await self.client.get_system_info()
            modem_mode = await self.client.get_modem_mode()
            cable = await self.client.get_cable_modem_state()
            downstream = await self.client.get_downstream_channels()
            upstream = await self.client.get_upstream_channels()
            service_flows = await self.client.get_service_flows()
            wifi_states = await self.client.get_wifi_states()
            hosts = await self.client.get_hosts(connected_only=False)
        except (CompalLockoutError, CompalAuthError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CompalSessionBusyError as err:
            # The web UI (or a prior client) holds the single session. Keep the
            # last-known values rather than flapping every entity to unavailable.
            if self.data is not None:
                _LOGGER.debug("Gateway session busy; keeping previous data: %s", err)
                return self.data
            raise UpdateFailed("Gateway session is busy (close the router web UI)") from err
        except CompalError as err:
            raise UpdateFailed(f"Error communicating with the gateway: {err}") from err
        finally:
            # Drop the bearer token so the router frees its single session slot.
            self.client.auth.clear()

        return {
            "system": system,
            "modem_mode": modem_mode,
            "cable": cable,
            "downstream": downstream,
            "upstream": upstream,
            "service_flows": service_flows,
            "wifi_states": wifi_states,
            "hosts": hosts,
            "signal": _signal_stats(downstream, upstream),
            "plan": _plan_rates(service_flows),
        }


def _signal_stats(downstream: list, upstream: list) -> dict:
    """Aggregate per-channel DOCSIS figures into a few headline numbers."""
    powers = [c.power for c in downstream if c.power is not None]
    snrs = [c.snr for c in downstream if c.snr is not None]
    corrected = sum(c.corrected_errors or 0 for c in downstream)
    uncorrected = sum(c.uncorrected_errors or 0 for c in downstream)
    return {
        "downstream_channels": len(downstream),
        "upstream_channels": len(upstream),
        "downstream_power_min": min(powers) if powers else None,
        "downstream_power_max": max(powers) if powers else None,
        "downstream_snr_min": min(snrs) if snrs else None,
        "corrected_errors": corrected,
        "uncorrected_errors": uncorrected,
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
    """Set up Compal F3896LG from a config entry."""
    session = async_get_clientsession(hass)
    client = CompalClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PASSWORD],
        session=session,
    )

    coordinator = CompalDataUpdateCoordinator(hass, client)
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
