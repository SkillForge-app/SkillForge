"""Questions monitor.sh asks Prometheus and Alertmanager (OPS-10). Runs inside the ai-metrics
container (it is on the compose network), so the host needs no Python:

    docker compose ... exec -T ai-metrics python /ops/monitor_query.py <command> [args]

Commands (exit 0 = yes / done, 1 = no / failed, 2 = usage):
    rules                          every group of ai/ops/alerts.yaml is loaded and healthy
    status                         targets, firing alerts, delivery counters
    firing NAME...                 each alert is firing in Prometheus
    known NAME...                  each alert fires in Prometheus or is still active in Alertmanager
    wait-firing SECONDS NAME...    wait until each alert fires in Prometheus and is in Alertmanager
    oncall                         prints "telegram" or "off": where the running Alertmanager sends
    counters                       prints "<accepted> <failed>": Telegram API requests so far
                                   (monitor.sh judges delivery from Alertmanager's log instead:
                                   these counters don't say WHICH alert was sent)
    value QUERY                    prints the value of an instant PromQL query (0 when empty)

Prints names, states and numbers only: never a token, chat id or log line.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

PROMETHEUS = "http://prometheus:9090"
ALERTMANAGER = "http://alertmanager:9093"
AI_ALERTS = Path("/ops-ai/alerts.yaml")


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read()


def prom(path: str) -> Any:
    return json.loads(get(PROMETHEUS + path))["data"]


def rules() -> int:
    wanted = {g["name"]: len(g["rules"]) for g in yaml.safe_load(AI_ALERTS.read_text())["groups"]}
    loaded = {g["name"]: g for g in prom("/api/v1/rules")["groups"]}
    bad = 0
    for name, count in wanted.items():
        group = loaded.get(name)
        if group is None:
            print(f"  MISSING  {name}: not loaded")
            bad += 1
            continue
        unhealthy = [r["name"] for r in group["rules"] if r.get("health") not in ("ok", "unknown")]
        ok = len(group["rules"]) == count and not unhealthy
        bad += not ok
        detail = f"unhealthy: {', '.join(unhealthy)}" if unhealthy else "healthy"
        print(f"  {'ok' if ok else 'BAD':8} {name}: {len(group['rules'])}/{count} rules, {detail}")
    total = sum(wanted.values())
    print(
        f"ai/ops/alerts.yaml: {len(wanted)} groups, {total} rules: "
        + ("loaded" if not bad else "PROBLEM")
    )
    return 1 if bad else 0


def prom_alerts() -> dict[str, str]:
    """alertname -> state ("firing" wins over "pending")."""
    states: dict[str, str] = {}
    for a in prom("/api/v1/alerts")["alerts"]:
        name = a["labels"]["alertname"]
        if states.get(name) != "firing":
            states[name] = a["state"]
    return states


def in_alertmanager(name: str, active_only: bool = False) -> bool:
    query = urllib.parse.quote(f'alertname="{name}"')
    alerts = json.loads(get(f"{ALERTMANAGER}/api/v2/alerts?filter={query}"))
    return any(not active_only or a["status"]["state"] == "active" for a in alerts)


def known(names: list[str]) -> int:
    """0 if every alert already fires: in Prometheus, or still active in Alertmanager (which then
    notified it already, and won't again within its repeat interval)."""
    states = prom_alerts()
    for name in names:
        if states.get(name) != "firing" and not in_alertmanager(name, active_only=True):
            return 1
    return 0


def firing(names: list[str]) -> int:
    states = prom_alerts()
    for name in names:
        print(f"  {name}: {states.get(name, 'inactive')}")
    return 0 if all(states.get(n) == "firing" for n in names) else 1


def wait_firing(seconds: float, names: list[str]) -> int:
    end = time.monotonic() + seconds
    while True:
        states = prom_alerts()
        ready = [n for n in names if states.get(n) == "firing" and in_alertmanager(n)]
        if len(ready) == len(names):
            for n in names:
                print(f"  {n}: firing in Prometheus, received by Alertmanager")
            return 0
        if time.monotonic() > end:
            for n in names:
                print(
                    f"  {n}: {states.get(n, 'inactive')}" + ("" if n in ready else " (not ready)")
                )
            return 1
        time.sleep(5)


def oncall() -> str:
    original = json.loads(get(f"{ALERTMANAGER}/api/v2/status"))["config"]["original"]
    return "telegram" if "telegram_configs" in original else "off"


def counters() -> tuple[float, float]:
    """Telegram API requests that succeeded, and that failed, since Alertmanager started.

    Per request, not per notification: alertmanager_notifications_failed_total counts a failure
    only once Alertmanager gives up retrying, so "notifications - failed" would count a message
    that is still failing as sent. A request that didn't fail is one Telegram accepted.
    """
    total = failed = 0.0
    for line in get(f"{ALERTMANAGER}/metrics").decode().splitlines():
        if line.startswith("#") or 'integration="telegram"' not in line:
            continue
        name, value = line.split("{", 1)[0], float(line.rsplit(" ", 1)[1])
        if name == "alertmanager_notification_requests_total":
            total += value
        elif name == "alertmanager_notification_requests_failed_total":
            failed += value
    return total - failed, failed


def value(query: str) -> str:
    result = prom("/api/v1/query?query=" + urllib.parse.quote(query))["result"]
    return f"{sum(float(r['value'][1]) for r in result):g}"


def status() -> int:
    print("  TARGET               HEALTH")
    for t in sorted(prom("/api/v1/targets")["activeTargets"], key=lambda t: t["labels"]["job"]):
        job = t["labels"]["job"]
        if job == "probe":
            job = f"probe {t['labels'].get('service', '?')}"
        print(f"  {job:20} {t['health']}")
    states = prom_alerts()
    firing_now = sorted(n for n, s in states.items() if s == "firing")
    pending = sorted(n for n, s in states.items() if s == "pending")
    print(f"  firing:  {', '.join(firing_now) or 'none'}")
    print(f"  pending: {', '.join(pending) or 'none'}")
    silences = json.loads(get(f"{ALERTMANAGER}/api/v2/silences"))
    active = sorted(
        {
            m["value"]
            for s in silences
            if s["status"]["state"] == "active"
            for m in s["matchers"]
            if m["name"] == "alertname"
        }
    )
    print(f"  silenced: {', '.join(active) or 'none'}")
    mode = oncall()
    ok, failed = counters()
    detail = (
        f" (Telegram: {ok:g} accepted, {failed:g} failed attempts)" if mode == "telegram" else ""
    )
    print(f"  on-call: {mode}{detail}")
    return rules()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, args = argv[0], argv[1:]
    if command == "rules":
        return rules()
    if command == "status":
        return status()
    if command == "firing" and args:
        return firing(args)
    if command == "known" and args:
        return known(args)
    if command == "wait-firing" and len(args) >= 2:
        return wait_firing(float(args[0]), args[1:])
    if command == "oncall":
        print(oncall())
        return 0
    if command == "counters":
        ok, failed = counters()
        print(f"{ok:g} {failed:g}")
        return 0
    if command == "value" and len(args) == 1:
        print(value(args[0]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
