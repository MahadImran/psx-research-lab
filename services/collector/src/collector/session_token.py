"""
PSX Session Token Provider.
Extracts and refreshes the mandatory window.__ps._k token embedded in PSX HTML pages.
Since 2026-09-24, PSX enforces X-Req-Id headers matching this token on data/XHR requests.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import re
import ssl
import time
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TOKEN_SCRIPT_RE = re.compile(r"window\.__ps\s*=\s*(\{.*?\})\s*(?:;|</script>)", re.DOTALL)
_TOKEN_VALID_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")


class PSXTokenProvider:
    def __init__(
        self,
        ttl_seconds: int = 3600,
        timeout_seconds: float = 10.0,
        budget_recorder: Optional[Any] = None,
    ):
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.budget_recorder = budget_recorder
        self._cached_token: Optional[str] = None
        self._cached_at: Optional[datetime] = None

    def is_token_valid(self) -> bool:
        if not self._cached_token or not self._cached_at:
            return False
        return (datetime.now(timezone.utc) - self._cached_at).total_seconds() < self.ttl_seconds

    def get_token(self, force_refresh: bool = False) -> Optional[str]:
        if not force_refresh and self.is_token_valid():
            return self._cached_token

        if self.budget_recorder is not None:
            self.budget_recorder.record_request("GET / (session token)")

        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                "https://dps.psx.com.pk/",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=self.timeout_seconds) as res:
                html = res.read().decode("utf-8", errors="ignore")

            match = _TOKEN_SCRIPT_RE.search(html)
            if not match:
                logger.warning("Could not find window.__ps payload in PSX homepage HTML")
                return None

            payload = json.loads(match.group(1))
            token = payload.get("_k")
            if token and _TOKEN_VALID_RE.match(token):
                self._cached_token = token
                self._cached_at = datetime.now(timezone.utc)
                return token
            else:
                logger.warning("Extracted token failed validation: %s", token)
                return None
        except Exception as e:
            logger.warning("Failed to refresh PSX session token: %s", e)
            return self._cached_token  # Return last known token if available

    def get_authenticated_headers(self, referer_path: str = "/") -> Dict[str, str]:
        token = self.get_token()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://dps.psx.com.pk{referer_path}",
            "Accept": "application/json, text/plain, text/javascript, */*",
        }
        if token:
            headers["X-Req-Id"] = token
        return headers
