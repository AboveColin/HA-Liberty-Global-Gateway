"""Config flow for the Compal / Sagemcom F3896LG (Ziggo) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from compalf3896lg import CompalClient
from compalf3896lg.exceptions import (
    CompalAuthError,
    CompalError,
    CompalLockoutError,
    CompalSessionBusyError,
)

from .const import CONF_HOST, CONF_PASSWORD, DEFAULT_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """The gateway could not be reached."""


class InvalidAuth(HomeAssistantError):
    """The admin password was rejected."""


class Lockout(HomeAssistantError):
    """The gateway login is temporarily locked out."""


class SessionBusy(HomeAssistantError):
    """Another session is active (the web UI is open)."""


async def _validate(hass, host: str, password: str) -> str:
    """Try a login against the gateway and return a title, or raise."""
    session = async_get_clientsession(hass)
    client = CompalClient(host, password, session=session)
    try:
        await client.login()
        try:
            info = await client.get_system_info()
        except CompalError:
            info = None
    except CompalLockoutError as err:
        raise Lockout(str(err)) from err
    except CompalAuthError as err:
        raise InvalidAuth(str(err)) from err
    except CompalSessionBusyError as err:
        raise SessionBusy(str(err)) from err
    except CompalError as err:
        raise CannotConnect(str(err)) from err
    finally:
        # Release the single session slot right away so the next step (or the
        # coordinator's first refresh) can log in without contention.
        await client.logout()

    model = getattr(info, "model_name", None)
    return f"Ziggo Gateway ({model})" if model else "Ziggo Cable Gateway"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the host + password setup for the F3896LG gateway."""

    VERSION = 1

    def __init__(self) -> None:
        self._entry: config_entries.ConfigEntry | None = None

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

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_PASSWORD): str,
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
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"host": host},
        )
