"""
Cloudflare Worker API Ingestion Client.
Sends HMAC-SHA256 signed ingestion payloads to the PSX Research Lab API,
passing Cloudflare Access service token credentials.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class IngestClient:
    def __init__(
        self,
        api_url: Optional[str] = None,
        hmac_secret: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout_seconds: float = 15.0,
    ):
        self.api_url = (
            api_url
            or os.environ.get("API_BASE_URL", "")
            or os.environ.get("INGEST_API_URL", "")
        ).rstrip("/")
        self.hmac_secret = hmac_secret or os.environ.get("INGEST_HMAC_SECRET", "")
        self.client_id = (
            client_id
            or os.environ.get("CLOUDFLARE_CLIENT_ID")
            or os.environ.get("CF_ACCESS_CLIENT_ID", "")
        )
        self.client_secret = (
            client_secret
            or os.environ.get("CLOUDFLARE_CLIENT_SECRET")
            or os.environ.get("CF_ACCESS_CLIENT_SECRET", "")
        )
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def compute_hmac_signature(secret: str, timestamp: int, nonce: str, raw_body: str) -> str:
        """Computes HMAC-SHA256(timestamp + '.' + nonce + '.' + raw_body)."""
        message = f"{timestamp}.{nonce}.{raw_body}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def send_ingestion(self, payload: Dict[str, Any]) -> Tuple[bool, int, Dict[str, Any]]:
        """
        Signs and delivers an IngestPayload to POST /v1/admin/ingest.
        Returns: (success, status_code, response_data)
        """
        raw_body = json.dumps(payload, indent=2, sort_keys=True)
        timestamp = int(time.time())
        nonce = uuid.uuid4().hex
        signature = self.compute_hmac_signature(self.hmac_secret, timestamp, nonce, raw_body)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PSXResearchLabCollector/1.0",
            "X-Ingest-Signature": signature,
            "X-Ingest-Timestamp": str(timestamp),
            "X-Ingest-Nonce": nonce,
        }

        # Attach Cloudflare Access service token headers if configured
        if self.client_id and self.client_secret:
            headers["CF-Access-Client-Id"] = self.client_id
            headers["CF-Access-Client-Secret"] = self.client_secret
            headers["X-Cloudflare-Client-Id"] = self.client_id
            headers["X-Cloudflare-Client-Secret"] = self.client_secret

        target_url = f"{self.api_url}/v1/admin/ingest"
        logger.info("Delivering ingestion payload to %s (timestamp: %d, nonce: %s)", target_url, timestamp, nonce)

        try:
            req = urllib.request.Request(
                target_url,
                data=raw_body.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return resp.status == 200, resp.status, resp_data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.warning("Ingest HTTP error %d: %s", e.code, err_body)
            try:
                err_data = json.loads(err_body)
            except Exception:
                err_data = {"error": f"HTTP {e.code}", "body": err_body}
            return False, e.code, err_data
        except Exception as e:
            logger.warning("Ingest client connection error: %s", e)
            return False, 0, {"error": str(e)}
