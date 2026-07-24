"""Tests for the Roulez Électrique button platform (manual refresh).

Covers:
  - a refresh button is created per charger
  - pressing it calls coordinator.async_request_refresh()
  - the button is always available, even when unavailable-by-default rules
    (coordinator failure / no charger data) would apply to other entities
  - unique_id scheme: "{charger_id}_refresh"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.roulezelectrique.button import RoulezElectriqueRefreshButton
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData

from .conftest import NON_OCPP_CHARGER, OCPP_CHARGER, WALLBOX_CHARGER


def _make_button(charger_data: dict[str, Any]) -> tuple[RoulezElectriqueRefreshButton, MagicMock]:
    """Create a refresh button with a mocked coordinator."""
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    button = RoulezElectriqueRefreshButton(coordinator, charger_id)
    button.async_write_ha_state = MagicMock()
    return button, coordinator


# ---------------------------------------------------------------------------
# async_setup_entry: one button per charger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_creates_one_button_per_charger():
    """async_setup_entry creates a refresh button for every charger, any vendor."""
    from custom_components.roulezelectrique.button import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 2: NON_OCPP_CHARGER, 3: WALLBOX_CHARGER},
        account=None,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert len(added) == 3
    charger_ids = sorted(e._charger_id for e in added)
    assert charger_ids == [1, 2, 3]
    assert all(isinstance(e, RoulezElectriqueRefreshButton) for e in added)


@pytest.mark.asyncio
async def test_setup_creates_no_buttons_when_no_chargers():
    """No chargers → no refresh buttons (nothing to refresh a device for)."""
    from custom_components.roulezelectrique.button import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={}, account=None)

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert added == []


# ---------------------------------------------------------------------------
# unique_id
# ---------------------------------------------------------------------------


def test_unique_id_scheme():
    button, _ = _make_button(OCPP_CHARGER)
    assert button._attr_unique_id == "1_refresh"


# ---------------------------------------------------------------------------
# async_press → coordinator.async_request_refresh()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_press_requests_coordinator_refresh():
    """Pressing the button forces an immediate coordinator refresh."""
    button, coordinator = _make_button(OCPP_CHARGER)

    await button.async_press()

    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Availability: always True, unlike every other entity in this integration
# ---------------------------------------------------------------------------


def test_button_available_when_charger_data_present():
    button, _ = _make_button(OCPP_CHARGER)
    assert button.available is True


def test_button_available_even_when_coordinator_has_no_data_for_charger():
    """A refresh button must keep working precisely when data is missing —
    that's exactly when a user needs to press it."""
    charger_id = OCPP_CHARGER["id"]
    coordinator = MagicMock()
    # No data at all for this charger (or for any charger).
    coordinator.data = CoordinatorData(chargers={}, account=None)
    coordinator.last_update_success = False
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    button = RoulezElectriqueRefreshButton(coordinator, charger_id)
    button.async_write_ha_state = MagicMock()

    assert button.available is True
