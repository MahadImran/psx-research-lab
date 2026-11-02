"""
Healthchecks.io Heartbeat Integration.
Sends lifecycle pings (start, success, fail) to the Healthchecks Hobbyist monitor.
Fails open: if the monitoring ping fails, the core collection process is not aborted.
Security: Completely redacts secret ping URLs from all log messages and exception outputs.
"""

from typing import Optional
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


class HealthchecksNotifier:
    def __init__(self, ping_url: Optional[str] = None):
        self.ping_url = (ping_url or os.environ.get("HEALTHCHECKS_PING_URL", "")).rstrip("/")

    @property
    def is_enabled(self) -> bool:
        return bool(self.ping_url and self.ping_url.startswith("http"))

    def _redacted_url(self) -> str:
        if not self.is_enabled:
            return "[NOT_CONFIGURED]"
        # Keep scheme and host, redact UUID token
        parts = self.ping_url.split("/")
        if len(parts) >= 4:
            return f"{parts[0]}//{parts[2]}/[REDACTED]"
        return "[REDACTED]"

    def _ping(self, endpoint: str = "", body: Optional[bytes] = None) -> bool:
        if not self.is_enabled:
            return False
        target_url = f"{self.ping_url}/{endpoint}".rstrip("/")
        try:
            req = urllib.request.Request(
                target_url,
                data=body,
                headers={"User-Agent": "PSXResearchLabCollector/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            logger.warning(
                "Healthchecks ping failed (HTTP %d) to endpoint '%s' at %s",
                e.code, endpoint or "root", self._redacted_url()
            )
            return False
        except Exception as e:
            # Avoid leaking raw URL in exception string
            sanitized_err = str(e).replace(self.ping_url, self._redacted_url())
            logger.warning(
                "Healthchecks ping error for endpoint '%s' at %s: %s",
                endpoint or "root", self._redacted_url(), sanitized_err
            )
            return False

    def ping_start(self) -> bool:
        return self._ping("start")

    def ping_success(self, summary_msg: str = "") -> bool:
        body = summary_msg.encode("utf-8") if summary_msg else None
        return self._ping("", body=body)

    def ping_fail(self, error_msg: str) -> bool:
        # Sanitize error message to ensure no secrets embedded
        sanitized = error_msg.replace(self.ping_url, self._redacted_url()) if self.ping_url else error_msg
        body = sanitized.encode("utf-8")
        return self._ping("fail", body=body)

    def ping_skip(self, reason: str) -> bool:
        # Pings with status message indicating market closed / skip
        body = f"SKIPPED: {reason}".encode("utf-8")
        return self._ping("", body=body)
