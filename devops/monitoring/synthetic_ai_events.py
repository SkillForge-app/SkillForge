"""Synthetic AI events for `monitor.sh test-cost` (OPS-17): proves the cost and budget alerts fire
and reach the on-call, without calling any model.

It logs, through AI's own code (core.llm.usage.log_call, core.ops.events.log_event, and the JSON
lines of core.ops.logs), exactly what the pipeline would log:
- 4 successful model calls of $5.00 each ($20 in a minute: AILLMSpendRateHigh, page, > $18.75/h),
  with tokens, so the dashboards show them;
- 1 analyze step stopped by its budget (AIBudgetExceeded, ticket).
Every record says model "ops-test/synthetic" and role "ops-test", so the dashboards and
OpsDemoKeySpendHigh leave them out of real spend. AI's 7-day windows (drift rules) still see the
$20: that's why monitor.sh refuses to run this in the demo codespace.

The service runs with no network. It waits 20 s before exiting, so ai-metrics (which looks for new
containers every 2 s) has started reading its logs before the container goes away.
"""

import sys
import time

from core.llm.usage import CallRecord, log_call
from core.ops.events import StepEvent, log_event
from core.ops.logs import install_json_logs

MODEL = "ops-test/synthetic"
ROLE = "ops-test"
CALLS = 4
COST_USD = 5.00


def main() -> int:
    install_json_logs(sys.stdout)
    run = f"ops-test-{int(time.time())}"
    for i in range(CALLS):
        log_call(
            CallRecord(
                call_id=f"{run}-{i}",
                kind="complete",
                model_role=ROLE,
                model=MODEL,
                input_tokens=2000,
                output_tokens=500,
                cost_usd=COST_USD,
                latency_ms=1000.0,
                status="ok",
                skill_run=run,
            )
        )
    log_event(
        StepEvent(
            step="analyze",
            status="failed",
            error_code="budget_exceeded",
            calls=0,
            cost_usd=0.0,
            latency_ms=1.0,
            skill_run=run,
        ),
        warning=True,
    )
    sys.stdout.flush()
    print(
        f"ops-test: logged {CALLS} calls (${CALLS * COST_USD:.2f}, model {MODEL})"
        " and 1 budget stop; waiting 20 s for ai-metrics",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
