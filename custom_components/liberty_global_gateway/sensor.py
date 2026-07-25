"""Sensor platform for the Liberty Global cable gateway integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS, UnitOfDataRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GatewayDataUpdateCoordinator
from .const import DOMAIN
from .entity import GatewayEntity


def _boot_time(data: dict) -> datetime | None:
    """Turn the modem's uptime (seconds) into a stable boot timestamp."""
    cable = data.get("cable")
    uptime = getattr(cable, "uptime", None)
    if uptime is None:
        return None
    return dt_util.utcnow().replace(microsecond=0) - timedelta(seconds=int(uptime))


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription(SensorEntityDescription):
    """Describes a gateway sensor and how to read its value."""

    value_fn: Callable[[dict], Any]
    attr_fn: Callable[[dict], dict[str, Any]] | None = None


def _downstream_attrs(data: dict) -> dict[str, Any]:
    signal = data.get("signal") or {}
    return {
        "channel_count": signal.get("downstream_channels"),
        "power_max_dbmv": signal.get("downstream_power_max"),
        "locked_channels": signal.get("downstream_locked"),
    }


def _upstream_attrs(data: dict) -> dict[str, Any]:
    signal = data.get("signal") or {}
    return {
        "channel_count": signal.get("upstream_channels"),
        "power_min_dbmv": signal.get("upstream_power_min"),
        "locked_channels": signal.get("upstream_locked"),
    }


# Wi-Fi band identifiers, as used across the gateway API.
_BAND_2G = "band2g"
_BAND_5G = "band5g"


def _wifi_cfg(data: dict, band: str, attr: str) -> Any:
    """Read one attribute from a band's Wi-Fi config, if present."""
    config = (data.get("wifi_configs") or {}).get(band)
    return getattr(config, attr, None) if config else None


def _last_event(data: dict):
    """Return the most recent event-log entry (newest first), if any."""
    log = data.get("event_log") or []
    return log[0] if log else None


def _wan_attrs(data: dict) -> dict[str, Any]:
    p = data.get("provisioning")
    if p is None:
        return {}
    return {
        "gateway": p.ipv4_gateway,
        "dns_servers": p.ipv4_dns,
        "ipv6_address": p.ipv6_global_address,
        "lease_time_seconds": p.ipv4_lease_time,
        "mode": p.mode,
    }


SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="docsis_status",
        translation_key="docsis_status",
        icon="mdi:transit-connection-variant",
        value_fn=lambda d: getattr(d.get("cable"), "status", None),
        attr_fn=lambda d: {
            "docsis_version": getattr(d.get("cable"), "docsis_version", None),
            "service_status": getattr(d.get("cable"), "service_status", None),
        },
    ),
    GatewaySensorDescription(
        key="uptime",
        translation_key="uptime",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_boot_time,
    ),
    GatewaySensorDescription(
        key="connected_devices",
        translation_key="connected_devices",
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="devices",
        value_fn=lambda d: sum(1 for h in (d.get("hosts") or []) if h.connected),
    ),
    GatewaySensorDescription(
        key="downstream_power_min",
        translation_key="downstream_power_min",
        icon="mdi:signal",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_power_min"),
        attr_fn=_downstream_attrs,
    ),
    GatewaySensorDescription(
        key="downstream_snr_min",
        translation_key="downstream_snr_min",
        icon="mdi:signal-cellular-3",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_snr_min"),
    ),
    GatewaySensorDescription(
        key="downstream_channels",
        translation_key="downstream_channels",
        icon="mdi:download-network",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_channels"),
    ),
    GatewaySensorDescription(
        key="upstream_channels",
        translation_key="upstream_channels",
        icon="mdi:upload-network",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("upstream_channels"),
    ),
    GatewaySensorDescription(
        key="corrected_errors",
        translation_key="corrected_errors",
        icon="mdi:alert-circle-check-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("corrected_errors"),
    ),
    GatewaySensorDescription(
        key="uncorrected_errors",
        translation_key="uncorrected_errors",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("uncorrected_errors"),
    ),
    GatewaySensorDescription(
        key="download_speed",
        translation_key="download_speed",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("plan") or {}).get("download_mbps"),
    ),
    GatewaySensorDescription(
        key="upload_speed",
        translation_key="upload_speed",
        icon="mdi:speedometer-medium",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("plan") or {}).get("upload_mbps"),
    ),
    GatewaySensorDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("system"), "software_version", None),
    ),
    GatewaySensorDescription(
        key="upstream_power_max",
        translation_key="upstream_power_max",
        icon="mdi:signal",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("upstream_power_max"),
        attr_fn=_upstream_attrs,
    ),
    GatewaySensorDescription(
        key="t3_timeouts",
        translation_key="t3_timeouts",
        icon="mdi:timer-alert-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="timeouts",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("t3_timeouts"),
    ),
    GatewaySensorDescription(
        key="t4_timeouts",
        translation_key="t4_timeouts",
        icon="mdi:timer-alert",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="timeouts",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("t4_timeouts"),
    ),
    GatewaySensorDescription(
        key="gateway_ip",
        translation_key="gateway_ip",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("lan"), "lan_ip", None),
    ),
    GatewaySensorDescription(
        key="ipv6_prefix",
        translation_key="ipv6_prefix",
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            f"{getattr(d.get('ipv6'), 'prefix_address', None)}/"
            f"{getattr(d.get('ipv6'), 'prefix_length', None)}"
            if getattr(d.get("ipv6"), "prefix_address", None)
            else None
        ),
    ),
    GatewaySensorDescription(
        key="wifi_2g_ssid",
        translation_key="wifi_2g_ssid",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _wifi_cfg(d, _BAND_2G, "ssid"),
        attr_fn=lambda d: {
            "channel": _wifi_cfg(d, _BAND_2G, "channel_number"),
            "channel_width": _wifi_cfg(d, _BAND_2G, "channel_width"),
            "security": _wifi_cfg(d, _BAND_2G, "security_type"),
        },
    ),
    GatewaySensorDescription(
        key="wifi_5g_ssid",
        translation_key="wifi_5g_ssid",
        icon="mdi:wifi",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _wifi_cfg(d, _BAND_5G, "ssid"),
        attr_fn=lambda d: {
            "channel": _wifi_cfg(d, _BAND_5G, "channel_number"),
            "channel_width": _wifi_cfg(d, _BAND_5G, "channel_width"),
            "security": _wifi_cfg(d, _BAND_5G, "security_type"),
        },
    ),
    GatewaySensorDescription(
        key="last_event",
        translation_key="last_event",
        icon="mdi:message-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            (_last_event(d).message or "")[:255] if _last_event(d) else None
        ),
        attr_fn=lambda d: (
            {
                "time": _last_event(d).time,
                "priority": _last_event(d).priority,
                "event_count": len(d.get("event_log") or []),
            }
            if _last_event(d)
            else {}
        ),
    ),
    GatewaySensorDescription(
        key="wan_ip",
        translation_key="wan_ip",
        icon="mdi:wan",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("provisioning"), "ipv4_address", None),
        attr_fn=_wan_attrs,
    ),
    GatewaySensorDescription(
        key="dns_servers",
        translation_key="dns_servers",
        icon="mdi:dns",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            ", ".join(getattr(d.get("provisioning"), "ipv4_dns", []) or []) or None
        ),
        attr_fn=lambda d: {
            "ipv4": getattr(d.get("provisioning"), "ipv4_dns", []) or [],
            "ipv6": getattr(d.get("provisioning"), "ipv6_dns", []) or [],
        },
    ),
    GatewaySensorDescription(
        key="software_update_status",
        translation_key="software_update_status",
        icon="mdi:package-up",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("software_update"), "status", None),
    ),
    GatewaySensorDescription(
        key="port_forward_rules",
        translation_key="port_forward_rules",
        icon="mdi:arrow-decision",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rules",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.get("port_forwarding") or []),
        attr_fn=lambda d: {
            "enabled": sum(1 for r in (d.get("port_forwarding") or []) if r.enabled)
        },
    ),
    GatewaySensorDescription(
        key="dhcp_reservations",
        translation_key="dhcp_reservations",
        icon="mdi:ip-network-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="reservations",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.get("reserved_ips") or []),
    ),
    GatewaySensorDescription(
        key="telephony_lines",
        translation_key="telephony_lines",
        icon="mdi:phone",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="lines",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: sum(
            1 for line in (d.get("mta_lines") or []) if line.operational
        ),
        attr_fn=lambda d: {"provisioned": len(d.get("mta_lines") or [])},
    ),
    GatewaySensorDescription(
        key="wan_gateway",
        translation_key="wan_gateway",
        icon="mdi:router-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("provisioning"), "ipv4_gateway", None),
    ),
    GatewaySensorDescription(
        key="wan_ipv6",
        translation_key="wan_ipv6",
        icon="mdi:ip-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("provisioning"), "ipv6_global_address", None),
    ),
    GatewaySensorDescription(
        key="wan_lease_time",
        translation_key="wan_lease_time",
        icon="mdi:timer-sand",
        native_unit_of_measurement="s",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("provisioning"), "ipv4_lease_time", None),
    ),
    GatewaySensorDescription(
        key="dhcp_pool",
        translation_key="dhcp_pool",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            f"{d['dhcp'].min_address} – {d['dhcp'].max_address}"
            if d.get("dhcp") and d["dhcp"].min_address
            else None
        ),
        attr_fn=lambda d: (
            {
                "lease_time_seconds": d["dhcp"].lease_time,
                "subnet_mask": d["dhcp"].subnet_mask,
                "enabled": d["dhcp"].enabled,
            }
            if d.get("dhcp")
            else {}
        ),
    ),
    GatewaySensorDescription(
        key="wifi_2g_channel",
        translation_key="wifi_2g_channel",
        icon="mdi:wifi-settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _wifi_cfg(d, _BAND_2G, "channel_number"),
    ),
    GatewaySensorDescription(
        key="wifi_5g_channel",
        translation_key="wifi_5g_channel",
        icon="mdi:wifi-settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _wifi_cfg(d, _BAND_5G, "channel_number"),
    ),
    GatewaySensorDescription(
        key="mac_filters",
        translation_key="mac_filters",
        icon="mdi:filter",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rules",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.get("mac_filters") or []),
    ),
    GatewaySensorDescription(
        key="port_triggers",
        translation_key="port_triggers",
        icon="mdi:filter-variant",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rules",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.get("port_triggers") or []),
    ),
    GatewaySensorDescription(
        key="ip_port_filters",
        translation_key="ip_port_filters",
        icon="mdi:filter-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rules",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.get("ip_port_filters") or []),
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the gateway sensors from a config entry."""
    coordinator: GatewayDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities(
        GatewaySensor(coordinator, config_entry.entry_id, description)
        for description in SENSORS
    )


class GatewaySensor(GatewayEntity, SensorEntity):
    """A single gateway sensor."""

    entity_description: GatewaySensorDescription

    def __init__(
        self,
        coordinator: GatewayDataUpdateCoordinator,
        entry_id: str,
        description: GatewaySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, if the description defines any."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data or {})

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
