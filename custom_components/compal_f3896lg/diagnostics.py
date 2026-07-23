"""Diagnostics support for the Compal / Sagemcom F3896LG integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {
    "password",
    "token",
    "access_token",
    "authorization",
    "serial_number",
    "mac_address",
    "ip_address",
    "ipv6_address",
    "hostname",
    "device_name",
    "ssid",
    "prefix_address",
    "lan_ip",
    # Never surface the Wi-Fi passphrase, even though it only lives on ``.raw``.
    "preSharedKey",
    "wpaPreSharedKey",
    "passphrase",
}


def _model_dump(obj: Any) -> Any:
    """Best-effort dict view of a library dataclass, dropping the raw payload."""
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return async_redact_data(raw, TO_REDACT)
    return str(obj)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (credentials and PII redacted)."""
    data: dict[str, Any] = {
        "entry": {
            "title": config_entry.title,
            "data": async_redact_data(config_entry.data, TO_REDACT),
        },
    }

    if config_entry.entry_id not in hass.data.get(DOMAIN, {}):
        data["error"] = "Integration not initialized"
        return data

    coordinator = hass.data[DOMAIN][config_entry.entry_id].get("coordinator")
    if coordinator:
        info: dict[str, Any] = {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        }
        cdata = coordinator.data or {}
        info["system"] = _model_dump(cdata.get("system"))
        info["cable"] = _model_dump(cdata.get("cable"))
        info["signal"] = cdata.get("signal")
        info["plan"] = cdata.get("plan")
        info["host_count"] = len(cdata.get("hosts") or [])
        data["coordinator"] = info

    return data
