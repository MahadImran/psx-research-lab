import pytest
from unittest.mock import patch, MagicMock
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.ingest_client import IngestClient


def test_hmac_signature_calculation():
    secret = "test-secret"
    timestamp = 1700000000
    nonce = "test-nonce-123"
    raw_body = '{"test": true}'

    sig = IngestClient.compute_hmac_signature(secret, timestamp, nonce, raw_body)
    assert len(sig) == 64  # SHA-256 hex string

    # Deterministic verification
    sig2 = IngestClient.compute_hmac_signature(secret, timestamp, nonce, raw_body)
    assert sig == sig2


def test_ingest_client_attaches_headers():
    client = IngestClient(
        api_url="https://api.psxresearchlab.com",
        hmac_secret="my-hmac-secret",
        client_id="cf-client-id",
        client_secret="cf-client-secret",
    )

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"status": "ACCEPTED"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {"collectorRunId": "test-run", "bars": []}
        ok, status, resp_data = client.send_ingestion(payload)

        assert ok is True
        assert status == 200
        assert resp_data["status"] == "ACCEPTED"

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.psxresearchlab.com/v1/admin/ingest"
        assert req.headers["Cf-access-client-id"] == "cf-client-id"
        assert req.headers["Cf-access-client-secret"] == "cf-client-secret"
        assert "X-ingest-signature" in req.headers
        assert "X-ingest-timestamp" in req.headers
        assert "X-ingest-nonce" in req.headers
