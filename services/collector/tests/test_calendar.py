import pytest
from datetime import datetime, time, date
import zoneinfo
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.calendar import MarketCalendar, PKT_ZONE


def test_market_calendar_karachi_timezone():
    now = MarketCalendar.now_pkt()
    assert now.tzinfo is not None
    assert str(now.tzinfo) == "Asia/Karachi"


def test_regular_session_monday():
    # Monday 2026-11-02 at 11:30 AM PKT -> Regular Session Open
    dt = datetime(2026, 11, 2, 11, 30, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt)
    assert session == "REGULAR_SESSION"
    assert is_open is True

    should_run, reason = MarketCalendar.should_scheduled_collector_run(dt)
    assert should_run is True
    assert "Market active" in reason


def test_pre_open_and_post_close_weekday():
    # Monday 08:30 AM PKT -> Pre-open
    dt_pre = datetime(2026, 11, 2, 8, 30, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_pre)
    assert session == "PRE_OPEN"
    assert is_open is False
    should_run, _ = MarketCalendar.should_scheduled_collector_run(dt_pre)
    assert should_run is False

    # Monday 16:00 PKT -> Post-close (within EOD reconciliation window 15:30-18:00)
    dt_post = datetime(2026, 11, 2, 16, 0, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_post)
    assert session == "POST_CLOSE"
    assert is_open is False
    should_run, reason = MarketCalendar.should_scheduled_collector_run(dt_post)
    assert should_run is True
    assert "EOD reconciliation window" in reason

    # Monday 21:00 PKT -> Closed (past EOD reconciliation window)
    dt_night = datetime(2026, 11, 2, 21, 0, tzinfo=PKT_ZONE)
    should_run_night, reason_night = MarketCalendar.should_scheduled_collector_run(dt_night)
    assert should_run_night is False
    assert "Market closed" in reason_night


def test_friday_split_sessions():
    # Friday 2026-11-06 10:30 AM PKT -> Session 1
    dt_fri1 = datetime(2026, 11, 6, 10, 30, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_fri1)
    assert session == "FRIDAY_SESSION_1"
    assert is_open is True

    # Friday 13:00 PKT -> Prayer Break
    dt_break = datetime(2026, 11, 6, 13, 0, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_break)
    assert session == "FRIDAY_PRAYER_BREAK"
    assert is_open is False

    # Friday 15:00 PKT -> Session 2
    dt_fri2 = datetime(2026, 11, 6, 15, 0, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_fri2)
    assert session == "FRIDAY_SESSION_2"
    assert is_open is True


def test_weekend_detection():
    # Saturday 2026-11-07
    dt_sat = datetime(2026, 11, 7, 12, 0, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_sat)
    assert session == "CLOSED_WEEKEND"
    assert is_open is False
    should_run, _ = MarketCalendar.should_scheduled_collector_run(dt_sat)
    assert should_run is False


def test_holiday_detection():
    # Kashmir Day 2026-02-05
    dt_hol = datetime(2026, 2, 5, 11, 0, tzinfo=PKT_ZONE)
    session, is_open = MarketCalendar.get_market_session(dt_hol)
    assert session == "CLOSED_HOLIDAY"
    assert is_open is False
    should_run, _ = MarketCalendar.should_scheduled_collector_run(dt_hol)
    assert should_run is False
