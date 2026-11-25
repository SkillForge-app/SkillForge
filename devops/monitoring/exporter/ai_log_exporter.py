"""ai-metrics: Prometheus metrics from the AI services' JSON-line logs (OPS-10, for AI-21's alerts).

    python ai_log_exporter.py                       # serve /metrics on :9464, following Docker logs
    python ai_log_exporter.py --selftest LOG.jsonl  # compare with AI's aggregator; exit 0 or 1

The rules are AI's, not ours: every log line goes through core.ops.metrics.aggregate() with the
specs of ai/ops/metrics.yaml (+ devops/monitoring/metrics.extra.yaml), and this module only adds
the results up over time and prints them in Prometheus' text format. So the metrics can't drift
from the file AI's alerts (ai/ops/alerts.yaml) were written against.

Input: the logs of every container of the compose project, read through the Docker Engine API of
the socket proxy (only GET /containers/json and /containers/{id}/logs are used; never inspect).
Only lines that are JSON objects whose `logger` starts with `skillforge.` count. They are
metadata-only by AI's policy, and this module never logs their contents.

Two details matter for the alerts:
- A restart must not count old lines again (that would look like a spend spike): containers that
  exist when the exporter starts are read from that moment on; later ones from their first line.
- Prometheus' increase() ignores the first sample of a new series, so a first-ever event (the first
  budget_exceeded) would never fire `increase(...) > 0`. Every new series is therefore shown at 0
  for HOLD_S seconds (two scrapes) before its value is added.

Standard library only (plus AI's code and its pydantic/yaml): it runs in the worker image.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from core.ops.metrics import METRICS_PATH, MetricsFile, aggregate, load_metrics, read_jsonl
except ImportError:  # run from a checkout without PYTHONPATH: use the repo's ai/
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ai"))
    from core.ops.metrics import METRICS_PATH, MetricsFile, aggregate, load_metrics, read_jsonl

EXTRA_PATH = Path(__file__).resolve().parents[1] / "metrics.extra.yaml"
HOLD_S = 35.0  # > 2 x the 15 s scrape interval (devops/monitoring/prometheus.yml)
POLL_S = 2.0
Labels = tuple[tuple[str, str], ...]


def log(message: str) -> None:
    print(f"ai-metrics: {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- specs


def load_specs(paths: Iterable[Path]) -> MetricsFile:
    """AI's file plus ours, as one spec. A metric name may appear once."""
    metrics = [m for path in paths for m in load_metrics(path).metrics]
    names = [m.name for m in metrics]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"metrics defined twice: {', '.join(duplicates)}")
    return MetricsFile(version=1, metrics=metrics)


# ---------------------------------------------------------------- the store


@dataclass
class _Series:
    """One label set. `pending` is added to the visible values once `ready_at` has passed."""

    ready_at: float
    value: float = 0.0  # counter, or histogram sum
    count: int = 0  # histogram only
    buckets: list[int] = field(default_factory=list)  # cumulative, histogram only
    p_value: float = 0.0
    p_count: int = 0
    p_buckets: list[int] = field(default_factory=list)

    def release(self, now: float) -> None:
        if now < self.ready_at or not (self.p_value or self.p_count):
            return
        self.value += self.p_value
        self.count += self.p_count
        self.buckets = [a + b for a, b in zip(self.buckets, self.p_buckets, strict=True)]
        self.p_value, self.p_count = 0.0, 0
        self.p_buckets = [0] * len(self.p_buckets)


class Store:
    def __init__(
        self, spec: MetricsFile, hold_s: float = HOLD_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.spec = spec
        self.by_name = {m.name: m for m in spec.metrics}
        self.hold_s = hold_s
        self.clock = clock
        self.series: dict[str, dict[Labels, _Series]] = {m.name: {} for m in spec.metrics}
        self.lines = {"metric": 0, "ignored": 0, "invalid": 0}
        self.lock = threading.Lock()

    def _get(self, name: str, labels: Labels, now: float) -> _Series:
        series = self.series[name].get(labels)
        if series is None:
            width = len(self.by_name[name].buckets) if self.by_name[name].type == "histogram" else 0
            series = _Series(ready_at=now + self.hold_s, buckets=[0] * width, p_buckets=[0] * width)
            self.series[name][labels] = series
        return series

    def observe(self, line: Mapping[str, Any]) -> bool:
        """Add one parsed log line. True if any metric counted it."""
        result = aggregate([line], self.spec)
        if not result.counters and not result.histograms:
            return False
        with self.lock:
            now = self.clock()
            for name, by_labels in result.counters.items():
                for labels, value in by_labels.items():
                    s = self._get(name, labels, now)
                    if now >= s.ready_at:
                        s.value += value
                    else:
                        s.p_value += value
            for name, by_labels in result.histograms.items():
                bounds = self.by_name[name].buckets
                for labels, values in by_labels.items():
                    s = self._get(name, labels, now)
                    live = now >= s.ready_at
                    for v in values:
                        hits = [1 if v <= b else 0 for b in bounds]
                        if live:
                            s.value, s.count = s.value + v, s.count + 1
                            s.buckets = [a + h for a, h in zip(s.buckets, hits, strict=True)]
                        else:
                            s.p_value, s.p_count = s.p_value + v, s.p_count + 1
                            s.p_buckets = [a + h for a, h in zip(s.p_buckets, hits, strict=True)]
        return True

    def feed(self, raw: str) -> None:
        """One raw log line (without Docker's timestamp)."""
        raw = raw.strip()
        if not raw.startswith("{"):
            self.lines["ignored"] += 1
            return
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            self.lines["invalid"] += 1
            return
        if not isinstance(line, dict) or not str(line.get("logger", "")).startswith("skillforge."):
            self.lines["ignored"] += 1
            return
        try:
            counted = self.observe(line)
        except (TypeError, ValueError):  # a field that isn't a number where a value is expected
            self.lines["invalid"] += 1
            return
        self.lines["metric" if counted else "ignored"] += 1

    def render(self, extra: Iterable[str] = ()) -> str:
        out: list[str] = []
        with self.lock:
            now = self.clock()
            for m in self.spec.metrics:
                out.append(f"# HELP {m.name} {_help(m.help)}")
                out.append(f"# TYPE {m.name} {m.type}")
                for labels, s in sorted(self.series[m.name].items()):
                    s.release(now)
                    if m.type == "counter":
                        out.append(f"{m.name}{_labels(labels)} {_num(s.value)}")
                        continue
                    for bound, n in zip(m.buckets, s.buckets, strict=True):
                        out.append(f"{m.name}_bucket{_labels(labels, le=_le(bound))} {n}")
                    out.append(f"{m.name}_bucket{_labels(labels, le='+Inf')} {s.count}")
                    out.append(f"{m.name}_sum{_labels(labels)} {_num(s.value)}")
                    out.append(f"{m.name}_count{_labels(labels)} {s.count}")
            out.append("# HELP skillforge_ops_exporter_lines_total Log lines read, by result.")
            out.append("# TYPE skillforge_ops_exporter_lines_total counter")
            for result, n in sorted(self.lines.items()):
                out.append(f'skillforge_ops_exporter_lines_total{{result="{result}"}} {n}')
        out.extend(extra)
        return "\n".join(out) + "\n"


def _help(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(labels: Labels, **more: str) -> str:
    pairs = [*labels, *more.items()]
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}" if pairs else ""


def _le(bound: float) -> str:
    return (
        "+Inf" if math.isinf(bound) else repr(float(bound))
    )  # 500 -> "500.0", like client libraries


def _num(value: float) -> str:
    return repr(float(value))


# ---------------------------------------------------------------- Docker logs


class Docker:
    """The two read-only calls this exporter makes, over plain HTTP to the socket proxy."""

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url.replace("tcp://", "http://"))
        if not parsed.hostname:
            raise ValueError(f"DOCKER_HOST must be tcp://host:port (got {url!r})")
        self.host, self.port = parsed.hostname, parsed.port or 2375

    def containers(self, project: str) -> list[dict[str, Any]]:
        filters = json.dumps({"label": [f"com.docker.compose.project={project}"]})
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            conn.request("GET", "/containers/json?all=1&filters=" + urllib.parse.quote(filters))
            response = conn.getresponse()
            body = response.read()
            if response.status != 200:
                raise OSError(f"GET /containers/json: HTTP {response.status}")
            return json.loads(body)
        finally:
            conn.close()

    def logs(self, container_id: str, since_s: int) -> Iterator[bytes]:
        """The container's output with Docker's timestamps, following it until it stops."""
        query = f"follow=1&stdout=1&stderr=1&timestamps=1&since={since_s}"
        conn = http.client.HTTPConnection(self.host, self.port, timeout=None)
        try:
            conn.request("GET", f"/containers/{container_id}/logs?{query}")
            response = conn.getresponse()
            if response.status != 200:
                raise OSError(f"GET /containers/{container_id[:12]}/logs: HTTP {response.status}")
            yield from _demux(response)
        finally:
            conn.close()


def _demux(response: http.client.HTTPResponse) -> Iterator[bytes]:
    """Lines of a log stream. Without a TTY, Docker frames each write with an 8-byte header."""
    buffer = b""
    framed: bool | None = None
    pending = b""
    while chunk := response.read1(65536):
        pending += chunk
        if framed is None:
            if len(pending) < 8:
                continue
            framed = pending[0] in (0, 1, 2) and pending[1:4] == b"\0\0\0"
        if framed:
            while len(pending) >= 8:
                size = int.from_bytes(pending[4:8], "big")
                if len(pending) < 8 + size:
                    break
                buffer += pending[8 : 8 + size]
                pending = pending[8 + size :]
        else:
            buffer, pending = buffer + pending, b""
        *lines, buffer = buffer.split(b"\n")
        yield from lines
    if buffer:
        yield buffer


_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z$")


def _ts_ns(text: str) -> int | None:
    """Docker's RFC 3339 timestamp, in nanoseconds since the epoch."""
    match = _TS.match(text)
    if not match:
        return None
    seconds = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp()
    fraction = (match[2] or "").ljust(9, "0")[:9]
    return int(seconds) * 1_000_000_000 + int(fraction)


@dataclass
class _Followed:
    active: bool
    last_ns: int


class Follower:
    """Finds the project's containers and feeds their logs to the store, each line once."""

    def __init__(self, docker: Docker, store: Store, project: str, exclude: set[str]) -> None:
        self.docker, self.store, self.project, self.exclude = docker, store, project, exclude
        self.start_ns = time.time_ns()
        self.followed: dict[str, _Followed] = {}
        self.lock = threading.Lock()

    def following(self) -> int:
        with self.lock:
            return sum(f.active for f in self.followed.values())

    def poll(self) -> None:
        for c in self.docker.containers(self.project):
            cid, labels = c["Id"], c.get("Labels") or {}
            service = labels.get("com.docker.compose.service", "?")
            if service in self.exclude:
                continue
            with self.lock:
                known = self.followed.get(cid)
                if known and (known.active or c.get("State") != "running"):
                    continue  # being read, or already read to its end
                if known:
                    since_ns = known.last_ns  # restarted: carry on after the last line read
                elif int(c.get("Created", 0)) * 1_000_000_000 < self.start_ns:
                    since_ns = self.start_ns  # older than this exporter: only new lines
                else:
                    since_ns = 0  # new: from its first line
                self.followed[cid] = _Followed(active=True, last_ns=since_ns)
            log(f"following {service} ({cid[:12]})")
            threading.Thread(target=self._follow, args=(cid, service), daemon=True).start()

    def _follow(self, cid: str, service: str) -> None:
        state = self.followed[cid]
        min_ns = state.last_ns
        try:
            for raw in self.docker.logs(cid, since_s=min_ns // 1_000_000_000):
                text = raw.decode("utf-8", errors="replace").rstrip("\r")
                stamp, _, rest = text.partition(" ")
                ns = _ts_ns(stamp)
                if ns is None:
                    continue
                if ns <= min_ns:  # `since` has whole-second precision: skip what was read before
                    continue
                state.last_ns = ns
                self.store.feed(rest)
        except OSError as error:
            log(f"{service} ({cid[:12]}): log stream ended: {type(error).__name__}")
        finally:
            with self.lock:
                state.active = False


# ---------------------------------------------------------------- HTTP


def serve(store: Store, follower: Follower | None, port: int, key_limit: float) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            if self.path == "/healthz":
                body, kind = b"ok\n", "text/plain"
            elif self.path == "/metrics":
                extra = [
                    "# HELP skillforge_ops_demo_key_limit_usd Credit limit of the demo's "
                    "OpenRouter key (DEMO_KEY_LIMIT_USD), for the OPS-17 spend rule.",
                    "# TYPE skillforge_ops_demo_key_limit_usd gauge",
                    f"skillforge_ops_demo_key_limit_usd {_num(key_limit)}",
                    "# HELP skillforge_ops_exporter_containers Containers whose logs are read now.",
                    "# TYPE skillforge_ops_exporter_containers gauge",
                    f"skillforge_ops_exporter_containers {follower.following() if follower else 0}",
                ]
                body, kind = store.render(extra).encode(), "text/plain; version=0.0.4"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # no access log

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 (container port)


# ---------------------------------------------------------------- self-test


def selftest(spec: MetricsFile, path: Path) -> int:
    """The store's totals must equal AI's aggregate() over the same file, and the hold must work."""
    lines = read_jsonl(path)
    reference = aggregate(lines, spec)
    store = Store(spec, hold_s=0)
    for raw in path.read_text(encoding="utf-8").splitlines():
        store.feed(raw)
    problems: list[str] = []
    for m in spec.metrics:
        got = store.series[m.name]
        if m.type == "counter":
            want = reference.counters.get(m.name, {})
            for labels in set(want) | set(got):
                a, b = want.get(labels, 0.0), got[labels].value if labels in got else 0.0
                if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
                    problems.append(f"{m.name}{_labels(labels)}: aggregate {a}, exporter {b}")
        else:
            want_h = reference.histograms.get(m.name, {})
            for labels in set(want_h) | set(got):
                values = want_h.get(labels, [])
                s = got.get(labels)
                expect = [sum(v <= b for v in values) for b in m.buckets]
                if (
                    s is None
                    or s.count != len(values)
                    or s.buckets != expect
                    or not math.isclose(s.value, sum(values), abs_tol=1e-9)
                ):
                    problems.append(f"{m.name}{_labels(labels)}: histogram differs")
    unused = [m.name for m in spec.metrics if not store.series[m.name]]
    # The hold: a new series shows 0 first, then its value.
    clock = [0.0]
    held = Store(spec, hold_s=HOLD_S, clock=lambda: clock[0])
    held.feed(json.dumps(next(ln for ln in lines if ln.get("logger") == "skillforge.llm")))
    first = held.render()
    clock[0] = HOLD_S + 1
    later = held.render()
    zero = re.search(r"^skillforge_llm_attempts_total\{.*\} 0\.0$", first, re.M)
    one = re.search(r"^skillforge_llm_attempts_total\{.*\} 1\.0$", later, re.M)
    if not (zero and one):
        problems.append("a new series is not shown at 0 before its first value")
    for line in store.render().splitlines():
        if (
            line
            and not line.startswith("#")
            and not re.match(r"^[a-zA-Z_:][\w:]*(\{.*\})? \S+$", line)
        ):
            problems.append(f"bad exposition line: {line[:80]}")
    counted = store.lines
    print(
        f"selftest: {len(lines)} JSON lines, lines {counted}, "
        f"{sum(len(s) for s in store.series.values())} series, "
        f"metrics without data in the fixture: {', '.join(unused) or 'none'}"
    )
    for p in problems:
        print(f"selftest: MISMATCH {p}")
    print("selftest: " + ("FAILED" if problems or unused else "ok"))
    return 1 if problems or unused else 0


# ---------------------------------------------------------------- main


def key_limit_from_env() -> float:
    raw = os.environ.get("DEMO_KEY_LIMIT_USD", "").strip() or "3"
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        raise SystemExit(f"ai-metrics: DEMO_KEY_LIMIT_USD must be a number > 0 (got {raw!r})")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_log_exporter.py")
    parser.add_argument(
        "--spec",
        type=Path,
        action="append",
        help=f"a metrics file (default: {METRICS_PATH} and {EXTRA_PATH})",
    )
    parser.add_argument("--selftest", type=Path, metavar="LOG.jsonl")
    parser.add_argument("--port", type=int, default=int(os.environ.get("EXPORTER_PORT", "9464")))
    args = parser.parse_args(argv)
    spec = load_specs(args.spec or [METRICS_PATH, EXTRA_PATH])
    if args.selftest:
        return selftest(spec, args.selftest)

    key_limit = key_limit_from_env()
    project = os.environ.get("COMPOSE_PROJECT", "skillforge")
    exclude = {s for s in os.environ.get("EXCLUDE_SERVICES", "").split(",") if s}
    store = Store(spec)
    follower = Follower(
        Docker(os.environ.get("DOCKER_HOST", "tcp://docker-socket-proxy:2375")),
        store,
        project,
        exclude,
    )
    threading.Thread(
        target=serve, args=(store, follower, args.port, key_limit), daemon=True
    ).start()
    log(f"serving /metrics on :{args.port}; {len(spec.metrics)} metrics; project {project}")
    while True:
        try:
            follower.poll()
        except OSError as error:
            log(f"docker API: {type(error).__name__}: {error}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
