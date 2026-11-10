"""Exposure refresh window: overlap the newest rows so outages get backfilled."""

import sys
import types
from datetime import date

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


def test_normal_day_rebuilds_last_three_days(exposure):
    assert exposure.refresh_start(date(2026, 11, 10), date(2026, 11, 8)) == date(2026, 11, 5)


def test_outage_is_backfilled_from_newest_present_day(exposure):
    assert exposure.refresh_start(date(2026, 11, 10), date(2026, 11, 1)) == date(2026, 10, 29)


def test_backfill_is_bounded(exposure):
    assert exposure.refresh_start(date(2026, 11, 10), date(2025, 1, 1)) == date(2026, 7, 13)
    assert exposure.refresh_start(date(2026, 11, 10), None) == date(2026, 11, 7)
