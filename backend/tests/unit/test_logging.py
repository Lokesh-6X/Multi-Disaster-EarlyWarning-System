"""JSON-line logging (design/14 §14.2, DD96, NFR-08)."""
import json
import logging
import logging.handlers
import re

import pytest

from ews.common import logging as ews_logging


@pytest.fixture
def log_dir(tmp_path):
    yield tmp_path
    ews_logging.shutdown()


def read_records(log_dir, process="ingest"):
    lines = (log_dir / f"{process}.log").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_record_is_one_json_line_with_required_fields(log_dir):
    """DD96: one JSON object per line with ts, level, process, event (14.2.1)."""
    log = ews_logging.setup_logging("ingest", log_dir)
    log.info("reading.stored", kit_id="KIT-01", duration_ms=12, qc="valid")
    lines = (log_dir / "ingest.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["process"] == "ingest"
    assert record["event"] == "reading.stored"
    assert record["kit_id"] == "KIT-01" and record["duration_ms"] == 12 and record["qc"] == "valid"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", record["ts"])


def test_msg_is_optional(log_dir):
    log = ews_logging.setup_logging("worker", log_dir)
    log.info("job.completed")
    log.warning("forecast.run_skipped", msg="previous run still busy")
    first, second = read_records(log_dir, "worker")
    assert "msg" not in first
    assert second["msg"] == "previous run still busy" and second["level"] == "WARNING"


def test_level_filter(log_dir):
    log = ews_logging.setup_logging("api", log_dir, level="INFO")
    log.debug("http.request", method="GET")
    log.info("http.request", method="POST")
    assert [r["method"] for r in read_records(log_dir, "api")] == ["POST"]


def test_error_field_has_type_message_and_stack(log_dir):
    """14.2.1: on errors, `error` holds exception type, message and stack trace."""
    log = ews_logging.setup_logging("worker", log_dir)
    try:
        raise ValueError("model file missing")
    except ValueError:
        log.exception("model.load_failed", model="tft-base-1.0.0")
    (record,) = read_records(log_dir, "worker")
    assert record["level"] == "ERROR"
    assert record["error"]["type"] == "ValueError"
    assert record["error"]["message"] == "model file missing"
    assert "Traceback" in record["error"]["stack"]


@pytest.mark.parametrize("field", [
    "password", "smtp_password", "MQTT_INGEST_PASSWORD", "password_hash", "secret_key",
    "session_cookie", "csrf_token", "reset_token", "invite_token",
])
def test_secret_fields_are_masked(log_dir, field):
    """NFR-08, 14.2.3: passwords, hashes, cookies, CSRF and invite/reset tokens are never logged."""
    log = ews_logging.setup_logging("api", log_dir)
    log.info("auth.login", **{field: "hunter2-secret"}, user_id=7)
    text = (log_dir / "api.log").read_text(encoding="utf-8")
    assert "hunter2-secret" not in text
    (record,) = read_records(log_dir, "api")
    assert record[field] == "***"
    assert record["user_id"] == 7


def test_password_inside_a_url_is_masked(log_dir):
    """NFR-08: a DATABASE_URL in a log line must not leak its password."""
    log = ews_logging.setup_logging("worker", log_dir)
    log.warning("db.reconnect", url="postgresql://ews:S3cretPw@localhost:5432/ews", msg="lost postgresql://ews:S3cretPw@db")
    text = (log_dir / "worker.log").read_text(encoding="utf-8")
    assert "S3cretPw" not in text
    (record,) = read_records(log_dir, "worker")
    assert record["url"] == "postgresql://ews:***@localhost:5432/ews"


def test_nested_secret_is_masked(log_dir):
    log = ews_logging.setup_logging("mailer", log_dir)
    log.info("email.sent", smtp={"host": "localhost", "password": "pw-123"})
    (record,) = read_records(log_dir, "mailer")
    assert record["smtp"] == {"host": "localhost", "password": "***"}


def test_account_link_fallback_keeps_its_token(log_dir):
    """14.2.3 exception: the WEB-03 fallback line deliberately shows the link."""
    log = ews_logging.setup_logging("mailer", log_dir)
    log.warning("account_link.fallback", link="http://localhost:8000/invite?token=abc123")
    (record,) = read_records(log_dir, "mailer")
    assert record["link"].endswith("token=abc123")


def test_rotation_10_mb_times_10(log_dir):
    """DD96, 14.2.4: rotating file handler, 10 MB per file, 10 files."""
    ews_logging.setup_logging("alerts", log_dir)
    handlers = [h for h in logging.getLogger("ews").handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 10 * 1024 * 1024
    assert handlers[0].backupCount == 10


def test_sim_time_added_in_demo_mode(log_dir):
    """14.2.1: in demo mode the demo clock time is logged next to the real ts."""
    log = ews_logging.setup_logging("alerts", log_dir, sim_time=lambda: "2024-05-27T14:00:00Z")
    log.info("alert.changed", alert_id=3)
    (record,) = read_records(log_dir, "alerts")
    assert record["sim_time"] == "2024-05-27T14:00:00Z"


def test_setup_twice_does_not_duplicate_lines(log_dir):
    ews_logging.setup_logging("ingest", log_dir)
    log = ews_logging.setup_logging("ingest", log_dir)
    log.info("mqtt.connected")
    assert len(read_records(log_dir)) == 1


def test_console_text_in_dev(log_dir, capsys):
    """14.2.1: with -Dev the console shows the same records as readable text."""
    log = ews_logging.setup_logging("ingest", log_dir, console=True)
    log.info("mqtt.connected", host="localhost", password="pw")
    err = capsys.readouterr().err
    assert "INFO" in err and "ingest" in err and "mqtt.connected" in err and "host=localhost" in err
    assert "pw" not in err.replace("password", "")
