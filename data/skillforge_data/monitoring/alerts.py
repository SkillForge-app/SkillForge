"""DE-11: the alert object, the notifier interface and structured log events.

A notifier is how an alert leaves the process. Nothing here talks to a real alerting system: OPS-10 (OpenTelemetry collector, alerts) is not
there yet, so `LogNotifier` writes the alert as a log event, and `ListNotifier` collects alerts for tests. When OPS-10 exists, a class
with the same `send(alert)` method is the only thing to add.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger("skillforge_data.monitoring")


class Severity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    check: str                                   # the name of the check, e.g. "failed_run"
    severity: Severity
    message: str                                 # one sentence for a person
    raised_at: datetime
    key: str                                     # the same problem has the same key, so a notifier can drop repeats
    details: dict[str, Any] = field(default_factory=dict)      # numbers and ids only: never page text or personal data

    def as_event(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        data["raised_at"] = self.raised_at.isoformat()
        return data


class Notifier(Protocol):
    def send(self, alert: Alert) -> None: ...


class LogNotifier:
    """Writes every alert as one structured log line (level WARNING or ERROR)."""

    def send(self, alert: Alert) -> None:
        level = logging.ERROR if alert.severity is Severity.CRITICAL else logging.WARNING
        logger.log(level, json.dumps({"event": "monitoring.alert", **alert.as_event()}, default=str, sort_keys=True))


class ListNotifier:
    """Keeps the alerts in memory (tests, and a dry run)."""

    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.alerts.append(alert)


def log_event(event: str, **fields: Any) -> None:
    """One structured log event: a JSON object on one line with an `event` name. Values must be numbers, ids and names."""
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))
