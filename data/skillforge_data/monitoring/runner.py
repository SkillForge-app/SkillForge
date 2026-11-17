"""DE-11: run all checks, log what happened, send the alerts to a notifier.

`run_checks` never raises because of a notifier or one failing check: a check that crashes becomes a critical alert of its own
("monitoring_error"), because a broken monitor must not look like a healthy system.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg

from .alerts import Alert, Notifier, Severity, log_event
from .checks import ALL_CHECKS, MonitoringConfig


@dataclass
class MonitoringReport:
    checks_run: int = 0
    alerts: list[Alert] = field(default_factory=list)
    notify_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.alerts


def run_checks(
    conn: psycopg.Connection,
    notifier: Notifier,
    *,
    now: datetime | None = None,
    config: MonitoringConfig | None = None,
    checks: Sequence[Callable[[psycopg.Connection, datetime, MonitoringConfig], list[Alert]]] = ALL_CHECKS,
) -> MonitoringReport:
    now = now or datetime.now(UTC)
    config = config or MonitoringConfig()
    report = MonitoringReport()
    for check in checks:
        name = check.__name__
        report.checks_run += 1
        try:
            with conn.transaction():                       # a savepoint: a failing query must not poison the connection
                alerts = check(conn, now, config)
        except Exception as exc:  # noqa: BLE001 - see the module docstring
            alerts = [Alert("monitoring_error", Severity.CRITICAL, f"check {name} crashed: {type(exc).__name__}", now,
                            f"monitoring_error:{name}", {"check": name, "error": str(exc)[:200]})]
        log_event("monitoring.check", check=name, alerts=len(alerts))
        report.alerts.extend(alerts)
    for alert in report.alerts:
        try:
            notifier.send(alert)
        except Exception as exc:  # noqa: BLE001 - one notifier failure must not hide the other alerts
            report.notify_errors.append(f"{alert.key}: {type(exc).__name__}: {exc}")
    log_event("monitoring.run", checks=report.checks_run, alerts=len(report.alerts), notify_errors=len(report.notify_errors),
              critical=sum(a.severity is Severity.CRITICAL for a in report.alerts))
    return report
