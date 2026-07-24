"""Button platform for the Roulez Électrique integration.

One "Refresh" button per charger device: pressing it calls
`coordinator.async_request_refresh()` — the exact same call every write
action (switch.py, number.py) already triggers on success — forcing an
immediate re-poll of the server's cached state.

Why this exists: HA's own writes (start/stop, lock, set current) already
self-refresh instantly, so HA→app changes are never stale. But a change made
OUTSIDE Home Assistant (e.g. from the Roulez Électrique mobile app) is only
ever picked up by HA's periodic poll (`DEFAULT_SCAN_INTERVAL` /
the `scan_interval` option, see const.py), up to that many seconds later.
Re-opening the HA companion app does NOT force a poll — it only re-reads HA
Core's already-cached state — so there was previously no way for a user to
force an immediate re-check from the app. This button is that action.

`async_request_refresh()` only re-reads the server's already-cached state (see
coordinator.py's module docstring) — it never calls a vendor API and cannot
itself fail in a way that needs a fail-closed HomeAssistantError, unlike the
switch/number write paths.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one refresh button per charger device."""
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]

    charger_map = coordinator.data.chargers if coordinator.data else {}
    entities = [
        RoulezElectriqueRefreshButton(coordinator, charger_id)
        for charger_id in charger_map
    ]
    async_add_entities(entities)


class RoulezElectriqueRefreshButton(RoulezElectriqueEntity, ButtonEntity):
    """A button that forces an immediate coordinator refresh.

    Always available, even when the coordinator's last update failed or this
    charger has no data yet (`RoulezElectriqueEntity.available` would
    otherwise report unavailable): a button whose only job is "check again
    now" must keep working exactly when the user most needs to press it.
    """

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    # A "check again now" maintenance action, not one of the charger's primary
    # controls (charge/lock switches, current slider) — categorise it as CONFIG
    # so HA files it under the device's Configuration section instead of
    # cluttering the main controls (matches HA-core reboot/reconnect buttons).
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._attr_unique_id = f"{charger_id}_refresh"

    @property
    def available(self) -> bool:
        """Always available — see the class docstring."""
        return True

    async def async_press(self) -> None:
        """Force an immediate coordinator refresh."""
        await self.coordinator.async_request_refresh()
