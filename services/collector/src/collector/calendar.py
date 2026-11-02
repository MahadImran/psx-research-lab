"""
PSX Trading Calendar and Market Hours Manager.
All market hours are evaluated in Asia/Karachi (PKT, UTC+5).

Regular Sessions:
  - Monday to Thursday: 09:15 - 15:30 PKT
Friday Sessions (Split):
  - Session 1: 09:15 - 12:00 PKT
  - Session 2: 14:30 - 16:30 PKT
"""

from datetime import datetime, time, date, timezone, timedelta
from typing import Optional, Tuple
import zoneinfo

PKT_ZONE = zoneinfo.ZoneInfo("Asia/Karachi")

# Standard Pakistan Public & Market Holidays (YYYY-MM-DD)
PSX_HOLIDAYS_2026 = {
    "2026-02-05",  # Kashmir Day
    "2026-03-20",  # Eid-ul-Fitr (Estimated)
    "2026-03-21",  # Eid-ul-Fitr Day 2
    "2026-03-22",  # Eid-ul-Fitr Day 3
    "2026-03-23",  # Pakistan Day
    "2026-05-01",  # Labour Day
    "2026-05-27",  # Eid-ul-Adha (Estimated)
    "2026-05-28",  # Eid-ul-Adha Day 2
    "2026-06-25",  # Ashura (9th Muharram)
    "2026-06-26",  # Ashura (10th Muharram)
    "2026-08-14",  # Independence Day
    "2026-08-26",  # Eid Milad-un-Nabi
    "2026-11-09",  # Iqbal Day
    "2026-12-25",  # Quaid-e-Azam Day / Christmas
}


class MarketCalendar:
    @staticmethod
    def now_pkt() -> datetime:
        return datetime.now(PKT_ZONE)

    @staticmethod
    def is_holiday(d: date) -> bool:
        return d.isoformat() in PSX_HOLIDAYS_2026

    @staticmethod
    def is_weekend(d: date) -> bool:
        # 5 = Saturday, 6 = Sunday
        return d.weekday() >= 5

    @classmethod
    def get_market_session(cls, dt: Optional[datetime] = None) -> Tuple[str, bool]:
        """
        Returns (session_name, is_open).
        Session names:
          - CLOSED_WEEKEND
          - CLOSED_HOLIDAY
          - PRE_OPEN
          - REGULAR_SESSION
          - FRIDAY_SESSION_1
          - FRIDAY_PRAYER_BREAK
          - FRIDAY_SESSION_2
          - POST_CLOSE
        """
        pkt_time = (dt or cls.now_pkt()).astimezone(PKT_ZONE)
        cur_date = pkt_time.date()
        cur_time = pkt_time.time()
        weekday = pkt_time.weekday()

        if cls.is_weekend(cur_date):
            return "CLOSED_WEEKEND", False

        if cls.is_holiday(cur_date):
            return "CLOSED_HOLIDAY", False

        # Monday to Thursday (0-3)
        if weekday < 4:
            if cur_time < time(9, 15):
                return "PRE_OPEN", False
            elif cur_time <= time(15, 30):
                return "REGULAR_SESSION", True
            else:
                return "POST_CLOSE", False

        # Friday (4)
        if weekday == 4:
            if cur_time < time(9, 15):
                return "PRE_OPEN", False
            elif cur_time <= time(12, 0):
                return "FRIDAY_SESSION_1", True
            elif cur_time < time(14, 30):
                return "FRIDAY_PRAYER_BREAK", False
            elif cur_time <= time(16, 30):
                return "FRIDAY_SESSION_2", True
            else:
                return "POST_CLOSE", False

        return "CLOSED", False

    @classmethod
    def should_scheduled_collector_run(cls, dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Determines whether a scheduled collection job should execute against live PSX.
        Includes a 30-minute grace window post-close for daily reconciliation.
        """
        session_name, is_open = cls.get_market_session(dt)
        if is_open:
            return True, f"Market active ({session_name})"

        pkt_time = (dt or cls.now_pkt()).astimezone(PKT_ZONE)
        cur_date = pkt_time.date()
        cur_time = pkt_time.time()
        weekday = pkt_time.weekday()

        if not cls.is_weekend(cur_date) and not cls.is_holiday(cur_date):
            # Allow EOD post-close collection window:
            # Mon-Thu: 15:30 to 18:00 PKT
            # Friday: 16:30 to 19:00 PKT
            close_time = time(16, 30) if weekday == 4 else time(15, 30)
            eod_window_end = time(19, 0) if weekday == 4 else time(18, 0)
            if close_time <= cur_time <= eod_window_end:
                return True, f"EOD reconciliation window ({session_name})"

        return False, f"Market closed ({session_name})"
