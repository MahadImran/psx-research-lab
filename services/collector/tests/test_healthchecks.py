import pytest
from unittest.mock import patch, MagicMock
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.healthchecks import HealthchecksNotifier


def test_healthchecks_disabled_without_url():
    hc = HealthchecksNotifier(ping_url="")
    assert hc.is_enabled is False
    assert hc.ping_start() is False
    assert hc.ping_success() is False
    assert hc.ping_fail("test error") is False
    assert hc.ping_skip("market closed") is False


def test_healthchecks_pings_lifecycle():
    secret_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    hc = HealthchecksNotifier(ping_url=f"https://hc-ping.com/{secret_uuid}")
    assert hc.is_enabled is True

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # 1. Start ping
        assert hc.ping_start() is True
        call_url = mock_urlopen.call_args[0][0].full_url
        assert call_url == f"https://hc-ping.com/{secret_uuid}/start"

        # 2. Success ping
        assert hc.ping_success("run ok") is True
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == f"https://hc-ping.com/{secret_uuid}"
        assert req.data == b"run ok"

        # 3. Fail ping
        assert hc.ping_fail("upstream error 503") is True
        req_fail = mock_urlopen.call_args[0][0]
        assert req_fail.full_url == f"https://hc-ping.com/{secret_uuid}/fail"
        assert req_fail.data == b"upstream error 503"

        # 4. Skip ping
        assert hc.ping_skip("weekend") is True
        req_skip = mock_urlopen.call_args[0][0]
        assert req_skip.full_url == f"https://hc-ping.com/{secret_uuid}"
        assert b"SKIPPED: weekend" in req_skip.data


def test_healthchecks_redacts_secret_url_on_errors(caplog):
    secret_uuid = "secret-token-super-private-uuid-12345"
    full_url = f"https://hc-ping.com/{secret_uuid}"
    hc = HealthchecksNotifier(ping_url=full_url)

    with caplog.at_level(logging.WARNING):
        with patch("urllib.request.urlopen", side_effect=OSError(f"Connection failed to {full_url}")):
            hc.ping_start()
            hc.ping_fail(f"Failed at {full_url}")

    # Check logs for leak of secret UUID
    log_text = caplog.text
    assert secret_uuid not in log_text
    assert "[REDACTED]" in log_text


def test_healthchecks_fails_open_on_network_error():
    hc = HealthchecksNotifier(ping_url="https://hc-ping.com/12345-uuid")
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        # Must not throw, fails open returning False
        assert hc.ping_start() is False
        assert hc.ping_success("summary") is False
        assert hc.ping_fail("err") is False
