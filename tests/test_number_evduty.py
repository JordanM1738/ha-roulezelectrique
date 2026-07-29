"""Tests for the EVduty/Elmec MaxCurrent number entity.

"Core"-only OCPP bornes reject SetChargingProfile with NotSupported, so
/power-limit can never work for them; the server exposes a separate
POST /chargers/{id}/max-current recipe instead. Covers:

  - entity created ONLY on `max_current_controllable`, and never alongside the
    SetChargingProfile entity (the two server flags are mutually exclusive)
  - bounds from max_current_min / max_current_max (+ defaults when omitted)
  - value: last applied, else the baseline ceiling; restored across restarts
  - success → refresh; confirmed_amps wins over the requested value
  - PARTIAL outcome (confirmed but reset failed) keeps the confirmed value and
    says so, rather than reporting a plain failure
  - total failure / charging-in-progress / offline / rate limit → revert
  - per-entity lock prevents overlap
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique.api import (
    ChargingInProgressError,
    OfflineError,
    RateLimitedError,
)
from custom_components.roulezelectrique.const import (
    DEFAULT_MAX_AMPS,
    DEFAULT_MIN_AMPS,
    DOMAIN,
)
from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.number import (
    RoulezElectriqueEvdutyMaxCurrentNumber,
    RoulezElectriqueMaxCurrentNumber,
)

from .conftest import (
    EVDUTY_CHARGER,
    MAX_CURRENT_APPLIED,
    MAX_CURRENT_CHANGE_REJECTED,
    MAX_CURRENT_RESET_FAILED,
    NON_OCPP_CHARGER,
    OCPP_CHARGER,
)


def _make_number(
    charger_data: dict[str, Any],
    set_return: dict[str, Any] | None = None,
    set_side_effect: Exception | None = None,
) -> tuple[RoulezElectriqueEvdutyMaxCurrentNumber, MagicMock, MagicMock]:
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    if set_side_effect is not None:
        client.set_max_current = AsyncMock(side_effect=set_side_effect)
    else:
        client.set_max_current = AsyncMock(return_value=set_return or MAX_CURRENT_APPLIED)

    number = RoulezElectriqueEvdutyMaxCurrentNumber(coordinator, client, charger_id)
    number.async_write_ha_state = MagicMock()
    return number, coordinator, client


# ── bounds / value ──────────────────────────────────────────────────────────


def test_bounds_come_from_max_current_fields():
    number, _, _ = _make_number(EVDUTY_CHARGER)
    assert number.native_min_value == 6.0
    assert number.native_max_value == 48.0


def test_bounds_fall_back_to_defaults_when_omitted():
    charger = {**EVDUTY_CHARGER, "max_current_min": None, "max_current_max": None}
    number, _, _ = _make_number(charger)
    assert number.native_min_value == float(DEFAULT_MIN_AMPS)
    assert number.native_max_value == float(DEFAULT_MAX_AMPS)


def test_max_never_falls_below_min():
    charger = {**EVDUTY_CHARGER, "max_current_min": 16, "max_current_max": 6}
    number, _, _ = _make_number(charger)
    assert number.native_max_value == 16.0


def test_value_defaults_to_the_baseline_ceiling():
    """Nothing reports the live MaxCurrent, so the slider parks at the baseline."""
    number, _, _ = _make_number(EVDUTY_CHARGER)
    assert number.native_value == 48.0


def test_available_gated_on_max_current_controllable():
    number, _, _ = _make_number(EVDUTY_CHARGER)
    assert number.available is True

    number2, _, _ = _make_number({**EVDUTY_CHARGER, "max_current_controllable": False})
    assert number2.available is False


# ── set: success ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_calls_max_current_endpoint_not_power_limit():
    """The whole point: this borne must never receive a SetChargingProfile."""
    number, coordinator, client = _make_number(EVDUTY_CHARGER)

    await number.async_set_native_value(24)

    client.set_max_current.assert_awaited_once_with(9, 24)
    client.set_power_limit.assert_not_called()
    coordinator.async_request_refresh.assert_awaited_once()
    assert number.native_value == 24.0


@pytest.mark.asyncio
async def test_confirmed_amps_wins_over_the_requested_value():
    """The borne is the authority on what it actually stored."""
    outcome = {**MAX_CURRENT_APPLIED, "confirmed_amps": 20}
    number, _, _ = _make_number(EVDUTY_CHARGER, set_return=outcome)

    await number.async_set_native_value(24)

    assert number.native_value == 20.0


@pytest.mark.asyncio
async def test_float_value_is_rounded_to_whole_amps():
    number, _, client = _make_number(EVDUTY_CHARGER)
    await number.async_set_native_value(23.6)
    client.set_max_current.assert_awaited_once_with(9, 24)


# ── set: partial outcome ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_outcome_keeps_confirmed_value_and_explains():
    """Confirmed on the borne but the applying reboot failed — not a plain failure.

    The borne may already hold the new value, so reverting the display would
    lie to the owner just as much as reporting success would.
    """
    number, _, _ = _make_number(EVDUTY_CHARGER, set_return=MAX_CURRENT_RESET_FAILED)

    with pytest.raises(HomeAssistantError) as err:
        await number.async_set_native_value(24)

    assert "24" in str(err.value)
    assert "reset_failed" in str(err.value)
    assert number.native_value == 24.0


# ── set: failures ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_failure_reverts_the_value():
    number, coordinator, _ = _make_number(
        EVDUTY_CHARGER, set_return=MAX_CURRENT_CHANGE_REJECTED
    )

    with pytest.raises(HomeAssistantError) as err:
        await number.async_set_native_value(24)

    assert "change_rejected" in str(err.value)
    assert number.native_value == 48.0  # back to the ceiling
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_charging_in_progress_is_reported_distinctly_from_offline():
    """409 charging_in_progress needs the opposite advice from 409 offline."""
    number, _, _ = _make_number(
        EVDUTY_CHARGER, set_side_effect=ChargingInProgressError("busy")
    )

    with pytest.raises(HomeAssistantError) as err:
        await number.async_set_native_value(24)

    message = str(err.value).lower()
    assert "session" in message
    assert "offline" not in message
    assert number.native_value == 48.0


@pytest.mark.asyncio
async def test_offline_reverts():
    number, _, _ = _make_number(EVDUTY_CHARGER, set_side_effect=OfflineError("offline"))

    with pytest.raises(HomeAssistantError) as err:
        await number.async_set_native_value(24)

    assert "offline" in str(err.value).lower()
    assert number.native_value == 48.0


@pytest.mark.asyncio
async def test_rate_limited_surfaces_retry_after():
    number, _, _ = _make_number(EVDUTY_CHARGER, set_side_effect=RateLimitedError(42))

    with pytest.raises(HomeAssistantError) as err:
        await number.async_set_native_value(24)

    assert "42" in str(err.value)
    assert number.native_value == 48.0


@pytest.mark.asyncio
async def test_overlapping_set_is_refused():
    number, _, _ = _make_number(EVDUTY_CHARGER)
    await number._lock.acquire()
    try:
        with pytest.raises(HomeAssistantError):
            await number.async_set_native_value(24)
    finally:
        number._lock.release()


# ── restore across restarts ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_last_applied_value_is_restored_on_startup():
    number, _, _ = _make_number(EVDUTY_CHARGER)
    restored = MagicMock()
    restored.native_value = 18.0
    number.async_get_last_number_data = AsyncMock(return_value=restored)

    await RoulezElectriqueEvdutyMaxCurrentNumber.async_added_to_hass(number)

    assert number.native_value == 18.0


# ── platform setup gating ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evduty_gets_the_max_current_entity_and_only_that_one():
    from custom_components.roulezelectrique.number import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 2: NON_OCPP_CHARGER, 9: EVDUTY_CHARGER},
        account=None,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    by_id = {e._charger_id: e for e in added}
    assert sorted(by_id) == [1, 9]  # Tesla (2) still excluded
    assert isinstance(by_id[1], RoulezElectriqueMaxCurrentNumber)
    assert isinstance(by_id[9], RoulezElectriqueEvdutyMaxCurrentNumber)
    # Exactly ONE slider for the EVduty borne — never two competing controls.
    assert sum(1 for e in added if e._charger_id == 9) == 1


@pytest.mark.asyncio
async def test_current_limit_controllable_wins_if_a_server_ever_sets_both():
    """Defensive: a server bug setting both flags must not create two sliders."""
    from custom_components.roulezelectrique.number import async_setup_entry

    both = {**EVDUTY_CHARGER, "current_limit_controllable": True}
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={9: both}, account=None)

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert len(added) == 1
    assert isinstance(added[0], RoulezElectriqueMaxCurrentNumber)


def test_unique_ids_never_collide_between_the_two_entities():
    """A borne flipping between the two paths must not inherit the other's history."""
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={9: EVDUTY_CHARGER}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}

    a = RoulezElectriqueMaxCurrentNumber(coordinator, MagicMock(), 9)
    b = RoulezElectriqueEvdutyMaxCurrentNumber(coordinator, MagicMock(), 9)
    assert a.unique_id != b.unique_id
