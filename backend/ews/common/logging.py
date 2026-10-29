"""JSON-line logging (design/14 §14.2, DD96).

    log = setup_logging("ingest", settings.log_dir, level=settings.log_level)
    log.info("reading.stored", kit_id="KIT-01", duration_ms=12)
    log.exception("model.load_failed", model="tft-base-1.0.0")

One JSON object per line in `<log_dir>/<process>.log`, rotated at 10 MB × 10. The first argument is the
stable `event` code; `msg=` is optional readable text; other keywords become fields. Secret fields
and passwords inside URLs are masked before anything is written (NFR-08, §14.2.3).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = "ews"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 10
MASK = "***"

# Field names that are never written (14.2.3); matched as a part of the name, any case
_SECRET_NAME = re.compile(r"password|passwd|secret|token|cookie|csrf|hash", re.IGNORECASE)
_URL_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")
# The WEB-03 fallback deliberately prints the account link (14.2.3)
_UNMASKED_EVENTS = {"account_link.fallback"}
_RESERVED = {"ts", "level", "process", "event", "msg", "error", "sim_time"}


def _mask(value: Any, key: str = "") -> Any:
    if key and _SECRET_NAME.search(key):
        return MASK
    if isinstance(value, dict):
        return {k: _mask(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask(v) for v in value]
    if isinstance(value, str):
        return _URL_PASSWORD.sub(r"\1" + MASK + "@", value)
    return value


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _Context(logging.Filter):
    """Adds the process name and, in demo mode, the demo clock time to every record."""

    def __init__(self, process: str, sim_time: Callable[[], str] | None):
        super().__init__()
        self.process = process
        self.sim_time = sim_time

    def filter(self, record: logging.LogRecord) -> bool:
        record.process_name = self.process
        record.sim_time = self.sim_time() if self.sim_time else None
        return True


def _payload(record: logging.LogRecord) -> dict[str, Any]:
    event = getattr(record, "event", None) or record.getMessage()
    fields: dict[str, Any] = getattr(record, "fields", {})
    if event not in _UNMASKED_EVENTS:
        fields = _mask(fields)
    out: dict[str, Any] = {"ts": _utc(record.created), "level": record.levelname,
                           "process": record.process_name, "event": event}
    msg = getattr(record, "msg_text", None)
    if msg:
        out["msg"] = msg if event in _UNMASKED_EVENTS else _mask(msg)
    if record.sim_time:
        out["sim_time"] = record.sim_time
    out.update(fields)
    if record.exc_info and record.exc_info[0]:
        etype, evalue, tb = record.exc_info
        out["error"] = {"type": etype.__name__, "message": _mask(str(evalue)),
                        "stack": _mask("".join(traceback.format_exception(etype, evalue, tb)))}
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_payload(record), ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Readable console lines for start.ps1 -Dev: same record, same masking."""

    def format(self, record: logging.LogRecord) -> str:
        p = _payload(record)
        head = f"{p.pop('ts')} {p.pop('level'):<8} {p.pop('process')} {p.pop('event')}"
        msg = p.pop("msg", None)
        error = p.pop("error", None)
        text = head + (f" {msg}" if msg else "") + "".join(f" {k}={v}" for k, v in p.items())
        return text + ("\n" + error["stack"] if error else "")


class EventLogger:
    """Logger whose first argument is the stable `event` code (14.2.2)."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(self, level: int, event: str, msg: str | None, exc_info: Any, fields: dict[str, Any]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        clashes = _RESERVED & fields.keys()
        if clashes:
            raise ValueError(f"reserved log field(s): {', '.join(sorted(clashes))}")
        self._logger.log(level, event, exc_info=exc_info, stacklevel=3,
                         extra={"event": event, "msg_text": msg, "fields": fields})

    def debug(self, event: str, msg: str | None = None, **fields: Any) -> None:
        self._log(logging.DEBUG, event, msg, None, fields)

    def info(self, event: str, msg: str | None = None, **fields: Any) -> None:
        self._log(logging.INFO, event, msg, None, fields)

    def warning(self, event: str, msg: str | None = None, **fields: Any) -> None:
        self._log(logging.WARNING, event, msg, None, fields)

    def error(self, event: str, msg: str | None = None, **fields: Any) -> None:
        self._log(logging.ERROR, event, msg, None, fields)

    def critical(self, event: str, msg: str | None = None, **fields: Any) -> None:
        self._log(logging.CRITICAL, event, msg, None, fields)

    def exception(self, event: str, msg: str | None = None, **fields: Any) -> None:
        """ERROR with the current exception in `error`."""
        self._log(logging.ERROR, event, msg, True, fields)


def get_logger(name: str | None = None) -> EventLogger:
    """Logger for a module (`get_logger(__name__)`); configured by `setup_logging`."""
    if name and name != ROOT and not name.startswith(ROOT + "."):
        name = f"{ROOT}.{name}"
    return EventLogger(logging.getLogger(name or ROOT))


def setup_logging(process: str, log_dir: Path | str, level: str = "INFO", console: bool = False,
                  sim_time: Callable[[], str] | None = None) -> EventLogger:
    """Configure the `ews` logger of this process; safe to call again (replaces the handlers)."""
    shutdown()
    root = logging.getLogger(ROOT)
    root.setLevel(level.upper())
    root.propagate = False
    context = _Context(process, sim_time)

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{process}.log", maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(context)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(TextFormatter())
        console_handler.addFilter(context)
        root.addHandler(console_handler)
    return EventLogger(root)


def shutdown() -> None:
    """Close and remove the handlers (end of process, or before reconfiguring)."""
    root = logging.getLogger(ROOT)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
