"""Sensor platform for the Compal / Sagemcom F3896LG integration."""

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

from . import CompalDataUpdateCoordinator
from .const import DOMAIN
from .entity import CompalEntity


def _boot_time(data: dict) -> datetime | None:
    """Turn the modem's uptime (seconds) into a stable boot timestamp."""
    cable = data.get("cable")
    uptime = getattr(cable, "uptime", None)
    if uptime is None:
        return None
    return dt_util.utcnow().replace(microsecond=0) - timedelta(seconds=int(uptime))


@dataclass(frozen=True, kw_only=True)
class CompalSensorDescription(SensorEntityDescription):
    """Describes a Compal sensor and how to read its value."""

    value_fn: Callable[[dict], Any]
    attr_fn: Callable[[dict], dict[str, Any]] | None = None


def _downstream_attrs(data: dict) -> dict[str, Any]:
    signal = data.get("signal") or {}
    return {
        "channel_count": signal.get("downstream_channels"),
        "power_max_dbmv": signal.get("downstream_power_max"),
    }


SENSORS: tuple[CompalSensorDescription, ...] = (
    CompalSensorDescription(
        key="docsis_status",
        translation_key="docsis_status",
        icon="mdi:transit-connection-variant",
        value_fn=lambda d: getattr(d.get("cable"), "status", None),
        attr_fn=lambda d: {
            "docsis_version": getattr(d.get("cable"), "docsis_version", None),
            "service_status": getattr(d.get("cable"), "service_status", None),
        },
    ),
    CompalSensorDescription(
        key="uptime",
        translation_key="uptime",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_boot_time,
    ),
    CompalSensorDescription(
        key="connected_devices",
        translation_key="connected_devices",
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="devices",
        value_fn=lambda d: sum(1 for h in (d.get("hosts") or []) if h.connected),
    ),
    CompalSensorDescription(
        key="downstream_power_min",
        translation_key="downstream_power_min",
        icon="mdi:signal",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_power_min"),
        attr_fn=_downstream_attrs,
    ),
    CompalSensorDescription(
        key="downstream_snr_min",
        translation_key="downstream_snr_min",
        icon="mdi:signal-cellular-3",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_snr_min"),
    ),
    CompalSensorDescription(
        key="downstream_channels",
        translation_key="downstream_channels",
        icon="mdi:download-network",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("downstream_channels"),
    ),
    CompalSensorDescription(
        key="upstream_channels",
        translation_key="upstream_channels",
        icon="mdi:upload-network",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("upstream_channels"),
    ),
    CompalSensorDescription(
        key="corrected_errors",
        translation_key="corrected_errors",
        icon="mdi:alert-circle-check-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("corrected_errors"),
    ),
    CompalSensorDescription(
        key="uncorrected_errors",
        translation_key="uncorrected_errors",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.get("signal") or {}).get("uncorrected_errors"),
    ),
    CompalSensorDescription(
        key="download_speed",
        translation_key="download_speed",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("plan") or {}).get("download_mbps"),
    ),
    CompalSensorDescription(
        key="upload_speed",
        translation_key="upload_speed",
        icon="mdi:speedometer-medium",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.get("plan") or {}).get("upload_mbps"),
    ),
    CompalSensorDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: getattr(d.get("system"), "software_version", None),
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Compal sensors from a config entry."""
    coordinator: CompalDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]["coordinator"]
    async_add_entities(
        CompalSensor(coordinator, config_entry.entry_id, description)
        for description in SENSORS
    )


class CompalSensor(CompalEntity, SensorEntity):
    """A single Compal gateway sensor."""

    entity_description: CompalSensorDescription

    def __init__(
        self,
        coordinator: CompalDataUpdateCoordinator,
        entry_id: str,
        description: CompalSensorDescription,
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
