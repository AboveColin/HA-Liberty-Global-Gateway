"""Config flow for the Liberty Global cable gateway integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_SERIAL,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)

from liberty_global_gateway import LibertyGatewayClient, probe
from liberty_global_gateway.exceptions import (
    GatewayAuthError,
    GatewayError,
    GatewayLockoutError,
    GatewaySessionBusyError,
)

from .const import CONF_HOST, CONF_PASSWORD, DEFAULT_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

# A bare `str` renders the secret in clear text in the config form. TextSelector
# with type PASSWORD makes the browser treat it as a password field.
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

# Addresses this gateway family is shipped on, tried in order when guessing a
# default for the manual form: Ziggo hands out 192.168.178.1, UPC / Virgin
# Media / Sunrise builds use 192.168.0.1.
FALLBACK_HOSTS = (DEFAULT_HOST, "192.168.0.1")


class CannotConnect(HomeAssistantError):
    """The gateway could not be reached."""


class InvalidAuth(HomeAssistantError):
    """The admin password was rejected."""


class Lockout(HomeAssistantError):
    """The gateway login is temporarily locked out."""


class SessionBusy(HomeAssistantError):
    """Another session is active (the web UI is open)."""


def _local_ipv4() -> str | None:
    """Best-effort local IPv4 address of this Home Assistant instance."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent; this only asks the kernel which source address
        # the default route would use.
        sock.connect(("1.1.1.1", 53))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


async def _suggest_host(hass) -> str:
    """Guess the gateway address, preferring one that actually answers.

    The gateway exposes an unauthenticated identification endpoint, so a
    candidate can be confirmed before it is ever shown to the user.
    """
    candidates: list[str] = []

    local_ip = await hass.async_add_executor_job(_local_ipv4)
    if local_ip:
        try:
            # The gateway is ".1" of its own /24 on every operator build.
            network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
            candidates.append(str(network.network_address + 1))
        except ValueError:
            pass
    candidates.extend(host for host in FALLBACK_HOSTS if host not in candidates)

    session = async_get_clientsession(hass)
    results = await asyncio.gather(
        *(probe(host, session=session) for host in candidates),
        return_exceptions=True,
    )
    for host, result in zip(candidates, results):
        if isinstance(result, Exception):
            continue
        if result is not None:
            return host

    return candidates[0]


async def _validate(hass, host: str, password: str) -> str:
    """Try a login against the gateway and return a title, or raise."""
    session = async_get_clientsession(hass)
    client = LibertyGatewayClient(host, password, session=session)
    try:
        await client.login()
        try:
            info = await client.get_system_info()
        except GatewayError:
            info = None
    except GatewayLockoutError as err:
        raise Lockout(str(err)) from err
    except GatewayAuthError as err:
        raise InvalidAuth(str(err)) from err
    except GatewaySessionBusyError as err:
        raise SessionBusy(str(err)) from err
    except GatewayError as err:
        raise CannotConnect(str(err)) from err
    finally:
        # Release the single session slot right away so the next step (or the
        # coordinator's first refresh) can log in without contention.
        await client.logout()

    # The unauthenticated endpoint knows the operator brand ("Ziggo SmartWifi
    # modem"), which makes a far better entry title than the bare model number.
    try:
        localization = await probe(host, session=session)
    except GatewayError:
        localization = None
    if localization is not None:
        return localization.display_name

    model = getattr(info, "model_name", None)
    return f"Cable Gateway ({model})" if model else "Cable Gateway"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup of a Liberty Global cable gateway."""

    VERSION = 1

    def __init__(self) -> None:
        self._entry: config_entries.ConfigEntry | None = None
        self._discovered_host: str | None = None
        self._discovered_title: str | None = None

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> FlowResult:
        """Handle a gateway announcing itself over SSDP.

        Discovery only fires when UPnP is enabled on the gateway, which is not
        the default on every operator build; the manual flow stays available.
        """
        location = discovery_info.ssdp_location or ""
        host = urlparse(location).hostname
        if not host:
            return self.async_abort(reason="cannot_connect")

        # Many devices answer the InternetGatewayDevice SSDP query. Confirm
        # this really is an LG-RDK gateway using the credential-free endpoint
        # before showing the user anything.
        session = async_get_clientsession(self.hass)
        try:
            localization = await probe(host, session=session)
        except GatewayError:
            localization = None
        if localization is None:
            return self.async_abort(reason="not_supported")

        upnp = discovery_info.upnp or {}
        unique_id = upnp.get(ATTR_UPNP_SERIAL) or upnp.get(ATTR_UPNP_UDN) or host
        await self.async_set_unique_id(str(unique_id))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        self._discovered_host = host
        self._discovered_title = localization.display_name
        self.context["title_placeholders"] = {"name": localization.display_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask only for the admin password of a discovered gateway."""
        assert self._discovered_host is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                title = await _validate(
                    self.hass, self._discovered_host, user_input[CONF_PASSWORD]
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Lockout:
                errors["base"] = "lockout"
            except SessionBusy:
                errors["base"] = "session_busy"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected gateway login failure")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: self._discovered_host,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _SECRET}),
            errors=errors,
            description_placeholders={
                "name": self._discovered_title or "Cable Gateway",
                "host": self._discovered_host,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the gateway address and admin password."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                title = await _validate(self.hass, host, user_input[CONF_PASSWORD])
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Lockout:
                errors["base"] = "lockout"
            except SessionBusy:
                errors["base"] = "session_busy"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected gateway login failure")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            suggested_host = host
        else:
            suggested_host = await _suggest_host(self.hass)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=suggested_host): str,
                    vol.Required(CONF_PASSWORD): _SECRET,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start re-authentication for an existing entry."""
        entry_id = self.context.get("entry_id")
        self._entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        if self._entry is None:
            return self.async_abort(reason="unknown_entry")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect a fresh password for an existing entry."""
        errors: dict[str, str] = {}
        assert self._entry is not None
        host = self._entry.data[CONF_HOST]
        if user_input is not None:
            try:
                await _validate(self.hass, host, user_input[CONF_PASSWORD])
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Lockout:
                errors["base"] = "lockout"
            except SessionBusy:
                errors["base"] = "session_busy"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected gateway re-authentication failure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._entry,
                    data={**self._entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _SECRET}),
            errors=errors,
            description_placeholders={"host": host},
        )
