"""Exposure refresh window: repair late data and gaps inside the feature window."""

import sys
import types
from datetime import date, timedelta

import pytest


@pytest.fixture
def exposure(monkeypatch):
    stub = types.ModuleType("data.client")
    stub.PROJECT_ID, stub.DATASET, stub.DATASET_EU = "p", "retention", "retention"
    monkeypatch.setitem(sys.modules, "data.client", stub)
    sys.modules.pop("data.exposure", None)
    import data
    monkeypatch.setattr(data, "client", stub, raising=False)
    from data import exposure as module
    yield module
    sys.modules.pop("data.exposure", None)


def _days(end: date, n: int, skip: set[date] = frozenset()) -> set[date]:
    return {end - timedelta(days=i) for i in range(n)} - set(skip)


def test_normal_day_rebuilds_last_days(exposure):
    present = _days(date(2026, 11, 8), 120)
    assert exposure.refresh_start(date(2026, 11, 10), present) == date(2026, 11, 5)


def test_outage_is_backfilled_from_newest_present_day(exposure):
    present = _days(date(2026, 11, 1), 120)
    assert exposure.refresh_start(date(2026, 11, 10), present) == date(2026, 10, 29)


def test_older_gap_is_repaired_after_newer_days_arrive(exposure):
    present = _days(date(2026, 11, 8), 120, skip={date(2026, 11, 2)})
    assert exposure.refresh_start(date(2026, 11, 10), present) == date(2026, 11, 2)


def test_backfill_is_bounded(exposure):
    assert exposure.refresh_start(date(2026, 11, 10), {date(2025, 1, 1)}) == date(2026, 7, 13)
    assert exposure.refresh_start(date(2026, 11, 10), set()) == date(2026, 11, 7)
