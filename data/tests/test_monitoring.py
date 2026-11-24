"""DE-11: the data-quality checks and the alert interface, on a real (throwaway) database."""
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from skillforge_data.monitoring import (
    ALL_CHECKS,
    ListNotifier,
    LogNotifier,
    MonitoringConfig,
    Severity,
    run_checks,
)
from skillforge_data.monitoring import checks as c

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
CONFIG = MonitoringConfig()


def add_run(db, *, status="succeeded", finished_ago=timedelta(hours=1), started_ago=None, fetched=0, unchanged=0, duplicate=0,
            blocked=0, failed=0, error=None):
    finished = None if status == "running" else NOW - finished_ago
    started = NOW - (started_ago if started_ago is not None else finished_ago + timedelta(minutes=10))
    return db.execute(
        "INSERT INTO knowledge.crawl_runs (started_at, finished_at, status, user_agent, pipeline_version, pages_fetched, "
        "pages_unchanged, pages_duplicate, pages_blocked, pages_failed, error) VALUES (%s, %s, %s, 'ua', 'p1', %s, %s, %s, %s, %s, %s) "
        "RETURNING id", (started, finished, status, fetched, unchanged, duplicate, blocked, failed, error)).fetchone()[0]


def add_document(db, n, *, fetched_ago=timedelta(hours=1), status="embedded", quality_ok=True, source_type="web_page", duplicate_of=None):
    source = db.execute("INSERT INTO knowledge.sources (url, host, source_type) VALUES (%s, 'x.org', %s) RETURNING id",
                        (f"https://x.org/{n}", source_type)).fetchone()[0]
    return db.execute(
        "INSERT INTO knowledge.documents (source_id, fetched_at, content_hash, pipeline_version, title, status, quality_ok, "
        "quality_reasons, duplicate_of) VALUES (%s, %s, %s, 'p1', 'T', %s, %s, %s, %s) RETURNING id",
        (source, NOW - fetched_ago, f"{n:064x}", status, quality_ok, [] if quality_ok else ["too_short"], duplicate_of)).fetchone()[0]


# --------------------------------------------------------------------------- the two checks the task asks for
def test_a_failed_run_raises_a_critical_alert_with_its_error(db):
    run = add_run(db, status="failed", failed=3, error="database unreachable")
    [alert] = c.failed_runs(db, NOW, CONFIG)
    assert alert.severity is Severity.CRITICAL and alert.check == "failed_run" and alert.key == f"failed_run:{run}"
    assert alert.details["error"] == "database unreachable" and alert.details["pages_failed"] == 3


def test_an_old_failed_run_outside_the_window_is_not_reported_again(db):
    add_run(db, status="failed", finished_ago=timedelta(days=3))
    assert c.failed_runs(db, NOW, CONFIG) == []


def test_an_empty_run_raises_a_critical_alert(db):
    run = add_run(db, status="succeeded")                      # all counters zero
    [alert] = c.empty_runs(db, NOW, CONFIG)
    assert alert.check == "empty_run" and alert.severity is Severity.CRITICAL and alert.details["run_id"] == str(run)


@pytest.mark.parametrize("counter", ["fetched", "unchanged", "duplicate", "blocked", "failed"])
def test_a_run_that_saw_any_page_is_not_empty(db, counter):
    add_run(db, status="partial", **{counter: 1})
    assert c.empty_runs(db, NOW, CONFIG) == []


def test_a_failed_run_is_not_also_reported_as_empty(db):
    add_run(db, status="failed")
    assert c.empty_runs(db, NOW, CONFIG) == [] and len(c.failed_runs(db, NOW, CONFIG)) == 1


# ----------------------------------------------------------------------------------------- the other checks
def test_a_run_stuck_in_running_is_reported_a_fresh_one_is_not(db):
    old = add_run(db, status="running", started_ago=timedelta(hours=8))
    add_run(db, status="running", started_ago=timedelta(minutes=20))
    [alert] = c.stuck_runs(db, NOW, CONFIG)
    assert alert.details["run_id"] == str(old)


def test_no_successful_run_for_n_days(db):
    assert [a.check for a in c.no_recent_success(db, NOW, CONFIG)] == ["no_recent_success"], "an empty history is also an alert"
    add_run(db, status="succeeded", finished_ago=timedelta(days=5), fetched=3)
    add_run(db, status="failed", finished_ago=timedelta(hours=1))
    [alert] = c.no_recent_success(db, NOW, CONFIG)
    assert alert.details["days"] == 3 and alert.details["last_success"]
    add_run(db, status="succeeded", finished_ago=timedelta(days=1), fetched=3)
    assert c.no_recent_success(db, NOW, CONFIG) == []


def test_the_threshold_n_is_configurable(db):
    add_run(db, status="succeeded", finished_ago=timedelta(days=5), fetched=3)
    assert c.no_recent_success(db, NOW, MonitoringConfig(max_days_without_success=7)) == []


def test_a_sudden_drop_in_volume_is_a_warning(db):
    for days, pages in ((6, 100), (5, 110), (4, 90), (3, 105), (2, 95)):
        add_run(db, finished_ago=timedelta(days=days), fetched=pages)
    latest = add_run(db, finished_ago=timedelta(hours=1), fetched=20)
    [alert] = c.volume_drop(db, NOW, CONFIG)
    assert alert.severity is Severity.WARNING and alert.details["run_id"] == str(latest)
    assert alert.details["usual"] == 100 and alert.details["pages"] == 20 and alert.details["ratio"] == 0.2


def test_a_small_history_and_a_normal_volume_raise_nothing(db):
    for days, pages in ((6, 100), (5, 110)):
        add_run(db, finished_ago=timedelta(days=days), fetched=pages)
    add_run(db, finished_ago=timedelta(hours=1), fetched=5)
    assert c.volume_drop(db, NOW, CONFIG) == [], "only 2 earlier runs: too little history to judge"
    add_run(db, finished_ago=timedelta(days=4), fetched=90)
    add_run(db, finished_ago=timedelta(minutes=30), fetched=95)
    assert c.volume_drop(db, NOW, CONFIG) == [], "the latest run has a normal volume"


def test_a_tiny_usual_volume_is_ignored(db):
    for days in (5, 4, 3, 2):
        add_run(db, finished_ago=timedelta(days=days), fetched=4)
    add_run(db, finished_ago=timedelta(hours=1), fetched=1)
    assert c.volume_drop(db, NOW, CONFIG) == []


def test_documents_stuck_before_embedded_are_reported_but_not_the_ones_that_should_not_be_embedded(db):
    add_document(db, 1, fetched_ago=timedelta(days=2), status="chunked")                  # stuck
    add_document(db, 2, fetched_ago=timedelta(days=2), status="embedded")                 # fine
    add_document(db, 3, fetched_ago=timedelta(hours=2), status="fetched")                 # too young to judge
    add_document(db, 4, fetched_ago=timedelta(days=2), status="fetched", quality_ok=False)   # rejected: no chunks by design
    add_document(db, 5, fetched_ago=timedelta(days=2), status="fetched", source_type="skill_md")   # an example file
    [alert] = c.unprocessed_documents(db, NOW, CONFIG)
    assert alert.details["count"] == 1 and alert.severity is Severity.WARNING


def test_a_duplicate_is_not_stuck(db):
    original = add_document(db, 1)
    add_document(db, 2, fetched_ago=timedelta(days=2), status="fetched", duplicate_of=original)
    assert c.unprocessed_documents(db, NOW, CONFIG) == []


def test_no_new_data_for_a_week(db):
    assert c.no_new_data(db, NOW, CONFIG) == [], "an empty database says nothing here (no_recent_success covers it)"
    add_document(db, 1, fetched_ago=timedelta(days=10))
    [alert] = c.no_new_data(db, NOW, CONFIG)
    assert alert.check == "no_new_data"
    add_document(db, 2, fetched_ago=timedelta(days=1))
    assert c.no_new_data(db, NOW, CONFIG) == []


# ---------------------------------------------------------------------------------------- runner and notifier
def test_a_healthy_system_raises_nothing(db):
    for days in (5, 4, 3, 2, 1):
        add_run(db, finished_ago=timedelta(days=days), fetched=100)
    add_document(db, 1)
    report = run_checks(db, ListNotifier(), now=NOW)
    assert report.ok and report.checks_run == len(ALL_CHECKS)


def test_the_runner_sends_every_alert_to_the_notifier(db):
    add_run(db, status="failed", error="boom")
    add_run(db, status="succeeded")
    notifier = ListNotifier()
    report = run_checks(db, notifier, now=NOW)
    assert {a.check for a in notifier.alerts} == {"failed_run", "empty_run", "no_recent_success"}
    assert notifier.alerts == report.alerts and not report.ok


def test_a_notifier_that_fails_does_not_stop_the_others(db):
    add_run(db, status="failed")
    add_run(db, status="succeeded")

    class Broken:
        def __init__(self):
            self.sent = []

        def send(self, alert):
            if alert.check == "failed_run":
                raise ConnectionError("alert system down")
            self.sent.append(alert)

    notifier = Broken()
    report = run_checks(db, notifier, now=NOW)
    assert any(a.check == "empty_run" for a in notifier.sent)
    assert len(report.notify_errors) == 1 and "ConnectionError" in report.notify_errors[0]


def test_a_check_that_crashes_becomes_an_alert_and_the_others_still_run(db):
    def broken(conn, now, config):
        conn.execute("SELECT * FROM knowledge.no_such_table")
        return []

    add_run(db, status="failed")
    report = run_checks(db, ListNotifier(), now=NOW, checks=(broken, c.failed_runs))
    assert {a.check for a in report.alerts} == {"monitoring_error", "failed_run"}
    assert db.execute("SELECT 1").fetchone()[0] == 1, "the connection is still usable"


def test_log_notifier_writes_structured_json(db, caplog):
    add_run(db, status="failed", error="HTTP 500")
    with caplog.at_level(logging.INFO, logger="skillforge_data.monitoring"):
        run_checks(db, LogNotifier(), now=NOW, checks=(c.failed_runs,))
    lines = [json.loads(r.getMessage()) for r in caplog.records]
    alert = next(x for x in lines if x["event"] == "monitoring.alert")
    assert alert["check"] == "failed_run" and alert["severity"] == "critical" and alert["raised_at"].startswith("2026-11-17")
    assert {x["event"] for x in lines} == {"monitoring.alert", "monitoring.check", "monitoring.run"}
    run = next(x for x in lines if x["event"] == "monitoring.run")
    assert run["alerts"] == 1 and run["critical"] == 1
    assert any(r.levelno == logging.ERROR for r in caplog.records if "monitoring.alert" in r.getMessage())
