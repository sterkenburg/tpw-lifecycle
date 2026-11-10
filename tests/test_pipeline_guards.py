"""Daily pipeline guard: never publish a snapshot built on stale view data."""

import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture
def pipeline(monkeypatch):
    """Import jobs/daily_pipeline.py with its BigQuery-touching modules stubbed."""
    for name in ["actions.crm", "actions.emails", "actions.flows", "actions.slack",
                 "data.client", "data.activity", "data.exposure", "data.leads",
                 "data.suppliers", "signals.cohort", "analytics.outcomes",
                 "analytics.projected_value"]:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for pkg in ["actions", "data", "signals", "analytics"]:
        mod = sys.modules.get(pkg) or types.ModuleType(pkg)
        monkeypatch.setitem(sys.modules, pkg, mod)
    for name in ["crm", "emails", "flows", "slack"]:
        setattr(sys.modules["actions"], name, sys.modules[f"actions.{name}"])
    for name in ["client", "activity", "exposure", "leads", "suppliers"]:
        setattr(sys.modules["data"], name, sys.modules[f"data.{name}"])
    spec = importlib.util.spec_from_file_location("daily_pipeline", ROOT / "jobs/daily_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _feed(latest: str) -> pd.DataFrame:
    return pd.DataFrame({"profile_id": ["1"], "event_date": [pd.Timestamp(latest)], "views": [3]})


def test_single_day_feed_has_gaps(pipeline):
    with pytest.raises(RuntimeError, match="missing day"):
        pipeline.check_view_freshness(_feed("2026-11-08"), date(2026, 11, 10))


def test_stale_data_stops_publication(pipeline):
    with pytest.raises(RuntimeError, match="stale"):
        pipeline.check_view_freshness(_feed("2026-11-01"), date(2026, 11, 10))


def test_empty_feed_stops_publication(pipeline):
    empty = pd.DataFrame({"profile_id": [], "event_date": pd.to_datetime([]), "views": []})
    with pytest.raises(RuntimeError, match="stale"):
        pipeline.check_view_freshness(empty, date(2026, 11, 10))


def _window(latest: str, skip: set[str] = frozenset()) -> pd.DataFrame:
    days = pd.date_range(end=pd.Timestamp(latest), periods=90, freq="D")
    rows = [{"profile_id": "1", "event_date": d, "views": 2}
            for d in days if str(d.date()) not in skip]
    return pd.DataFrame(rows)


def test_complete_window_passes(pipeline):
    assert pipeline.check_view_freshness(_window("2026-11-08"), date(2026, 11, 10))


def test_gap_inside_window_stops_publication(pipeline):
    gap = {f"2026-11-0{d}" for d in range(2, 7)}
    with pytest.raises(RuntimeError, match="missing day"):
        pipeline.check_view_freshness(_window("2026-11-08", gap), date(2026, 11, 10))
