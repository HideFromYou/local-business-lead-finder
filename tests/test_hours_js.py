"""Runs web/hours.js under node. Skipped when node is not installed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOURS_JS = Path(__file__).resolve().parents[1] / "web" / "hours.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(place, year_month_day_hour_min):
    y, mo, d, h, mi = year_month_day_hour_min  # LOCAL time, month 1-12
    script = f"""
      const {{ openStatus, todayHours }} = require({json.dumps(str(HOURS_JS))});
      const now = new Date({y}, {mo - 1}, {d}, {h}, {mi});
      console.log(JSON.stringify({{ status: openStatus({json.dumps(place)}, now), today: todayHours({json.dumps(place)}, now) }}));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def period(day, open_h, close_h, close_day=None):
    return {"open": {"day": day, "hour": open_h, "minute": 0},
            "close": {"day": day if close_day is None else close_day, "hour": close_h, "minute": 0}}


MON_SAT = {"opening_periods": [period(d, 8, 21) for d in (1, 2, 3, 4, 5, 6)],
           "opening_hours": ["Δευτέρα: 8:00 π.μ.–9:00 μ.μ.", "Τρίτη: 8:00 π.μ.–9:00 μ.μ.", "Κυριακή: Κλειστό"]}
# 2026-10-05 is a Monday, 2026-10-04 a Sunday, 2026-10-06 a Tuesday.


def test_open_during_hours_shows_closing_time_and_todays_line():
    r = run(MON_SAT, (2026, 10, 5, 12, 30))
    assert r["status"] == {"state": "open", "label": "Ανοιχτό · κλείνει 21:00"}
    assert r["today"] == "8:00 π.μ.–9:00 μ.μ."


def test_closed_in_the_evening_opens_tomorrow():
    r = run(MON_SAT, (2026, 10, 5, 22, 0))
    assert r["status"] == {"state": "closed", "label": "Κλειστό · ανοίγει αύριο 08:00"}


def test_closed_before_opening_opens_today():
    assert run(MON_SAT, (2026, 10, 5, 6, 0))["status"]["label"] == "Κλειστό · ανοίγει σήμερα 08:00"


def test_closed_on_sunday_opens_monday_tomorrow():
    r = run(MON_SAT, (2026, 10, 4, 11, 0))
    assert r["status"]["label"] == "Κλειστό · ανοίγει αύριο 08:00"
    assert r["today"] == "Κλειστό"


def test_boundaries_open_at_opening_closed_at_closing():
    assert run(MON_SAT, (2026, 10, 5, 8, 0))["status"]["state"] == "open"
    assert run(MON_SAT, (2026, 10, 5, 21, 0))["status"]["state"] == "closed"


def test_open_past_midnight():
    bar = {"opening_periods": [period(5, 20, 2, close_day=6)]}  # Friday 20:00 -> Saturday 02:00
    assert run(bar, (2026, 10, 10, 1, 0))["status"]["label"] == "Ανοιχτό · κλείνει 02:00"  # Saturday 01:00
    assert run(bar, (2026, 10, 10, 3, 0))["status"]["state"] == "closed"


def test_always_open_has_no_closing_time():
    assert run({"opening_periods": [{"open": {"day": 0, "hour": 0, "minute": 0}, "close": None}]},
               (2026, 10, 7, 3, 0))["status"] == {"state": "open", "label": "Ανοιχτό 24 ώρες"}


def test_unknown_and_permanently_closed():
    assert run({}, (2026, 10, 5, 12, 0))["status"]["state"] == "unknown"
    assert run({**MON_SAT, "business_status": "CLOSED_PERMANENTLY"}, (2026, 10, 5, 12, 0))["status"]["state"] == "gone"


def test_old_server_string_format_does_not_break_the_page():
    old = {"opening_hours": "Δευτέρα: 8:00–21:00; Τρίτη: 8:00–21:00", "opening_periods": None}
    r = run(old, (2026, 10, 5, 12, 0))
    assert r["today"] == "8:00–21:00" and r["status"]["state"] == "unknown"
