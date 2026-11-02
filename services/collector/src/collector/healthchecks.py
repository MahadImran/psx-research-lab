"""
Healthchecks.io Heartbeat Integration.
Sends lifecycle pings (start, success, fail) to the Healthchecks Hobbyist monitor.
Fails open: if the monitoring ping fails, the core collection process is not aborted.
"""

from typing import Optional
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


class HealthchecksNotifier:
    def __init__(self, ping_url: Optional[str] = None):
        self.ping_url = (ping_url or os.environ.get("HEALTHCHECKS_PING_URL", "")).rstrip("/")

    @property
    def is_enabled(self) -> bool:
        return bool(self.ping_url and self.ping_url.startswith("http"))

    def _ping(self, endpoint: str = "", body: Optional[bytes] = None) -> bool:
        if not self.is_enabled:
            return False
        url = f"{self.ping_url}/{endpoint}".rstrip("/")
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"User-Agent": "PSXResearchLabCollector/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Healthchecks ping failed to %s: %s", url, e)
            return False

    def ping_start(self) -> bool:
        return self._ping("start")

    def ping_success(self, summary_msg: str = "") -> bool:
        body = summary_msg.encode("utf-8") if summary_msg else None
        return self._ping("", body=body)

    def ping_fail(self, error_msg: str) -> bool:
        body = error_msg.encode("utf-8")
        return self._ping("fail", body=body)

    def ping_skip(self, reason: str) -> bool:
        # Pings with status message indicating market closed / skip
        body = f"SKIPPED: {reason}".encode("utf-8")
        return self._ping("", body=body)
