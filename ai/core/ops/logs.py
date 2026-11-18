"""JSON-lines output for the metadata-only logs (AI-21), for OPS-10's collector.

    install_json_logs(sys.stdout)       # once, at startup (BE worker, scripts, tests)

Every record from the `skillforge.*` loggers becomes one JSON object per line:
    {"ts": "...", "level": "INFO", "logger": "skillforge.llm", "record": {...CallRecord...}}
`record` is the structured payload each logger attaches (CallRecord, a safety decision or an
ops event), so the collector derives metrics from fields, never by parsing messages. Records
without a payload (plain warnings) carry only `message`, which our code keeps free of content.
"""

import json
import logging
from datetime import UTC, datetime
from typing import IO, Any

PAYLOAD_ATTRS = ("llm_call", "safety_decision", "skillforge_event")
LOGGERS = ("skillforge.llm", "skillforge.safety", "skillforge.pipeline", "skillforge.knowledge",
           "skillforge.quality")  # fmt: skip


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        payload = next((getattr(record, a) for a in PAYLOAD_ATTRS if hasattr(record, a)), None)
        if payload is not None:
            line["record"] = payload
        else:
            line["message"] = record.getMessage()
        return json.dumps(line, default=str)


def install_json_logs(stream: IO[str], level: int = logging.INFO) -> logging.Handler:
    """Send the skillforge.* loggers to `stream` as JSON lines. Returns the handler."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLinesFormatter())
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(min(logger.level or level, level))
    return handler


def remove_json_logs(handler: logging.Handler) -> None:
    for name in LOGGERS:
        logging.getLogger(name).removeHandler(handler)
