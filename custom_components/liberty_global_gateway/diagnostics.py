"""Diagnostics support for the Liberty Global cable gateway integration."""

from __future__ import annotations

import re
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Event-log messages are free text that can embed MAC addresses
# (e.g. "CM-MAC=aa:bb:cc:dd:ee:ff"); scrub them before diagnostics leave the box.
_MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")

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
    if is_dataclass(obj) and not isinstance(obj, type):
        # Models without a ``.raw`` dict (lan, ipv6, registration, system, cable,
        # modem_mode, software_update and the rest) still carry field names that
        # TO_REDACT matches. Falling through to str() here would have written the
        # full repr, IP addresses and serial included, into the diagnostics file.
        return async_redact_data(
            {
                field.name: _model_dump(getattr(obj, field.name))
                for field in dataclass_fields(obj)
                if field.name != "raw"
            },
            TO_REDACT,
        )
    if isinstance(obj, dict):
        return async_redact_data(
            {key: _model_dump(value) for key, value in obj.items()}, TO_REDACT
        )
    if isinstance(obj, (list, tuple)):
        return [_model_dump(item) for item in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    # Nothing left to key redaction off, so scrub MACs out of the repr.
    return _MAC_RE.sub("**REDACTED**", str(obj))


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
        info["modem_mode"] = _model_dump(cdata.get("modem_mode"))
        info["lan"] = _model_dump(cdata.get("lan"))
        info["ipv6"] = _model_dump(cdata.get("ipv6"))
        info["wifi"] = {
            band: _model_dump(cfg)
            for band, cfg in (cdata.get("wifi_configs") or {}).items()
        }
        info["registration"] = _model_dump(cdata.get("registration"))
        # Provisioning carries the public IP + WAN MAC; report only safe shape.
        prov = cdata.get("provisioning")
        info["provisioning"] = (
            {
                "mode": prov.mode,
                "ipv4_present": bool(prov.ipv4_address),
                "ipv6_present": bool(prov.ipv6_global_address),
                "ipv4_lease_time": prov.ipv4_lease_time,
            }
            if prov
            else None
        )
        info["software_update"] = _model_dump(cdata.get("software_update"))
        info["features"] = {
            "upnp": cdata.get("upnp"),
            "smart_wifi": cdata.get("smart_wifi"),
            "dmz": getattr(cdata.get("dmz"), "enabled", None),
            "firewall": getattr(cdata.get("firewall"), "enabled", None),
            "port_forward_rules": len(cdata.get("port_forwarding") or []),
            "dhcp_reservations": len(cdata.get("reserved_ips") or []),
            "telephony_lines": len(cdata.get("mta_lines") or []),
        }
        info["signal"] = cdata.get("signal")
        info["plan"] = cdata.get("plan")
        info["host_count"] = len(cdata.get("hosts") or [])
        # Recent event-log lines (already free of PII), newest first.
        info["event_log"] = [
            {
                "time": e.time,
                "priority": e.priority,
                "message": _MAC_RE.sub("**:**:**:**:**:**", e.message or ""),
            }
            for e in (cdata.get("event_log") or [])[:15]
        ]
        data["coordinator"] = info

    return data
