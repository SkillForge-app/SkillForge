"""What an architect evaluation run will cost, before it runs (AI-07 pre-flight). No model call.

The input side is measured: every request's architect/generate prompt is rendered as it will be
sent, the SkillSpec response schema is added (LiteLLM sends it with every call), and characters
become tokens with a ratio measured on a live run of a prompt of this family (CALIBRATION).

The output side cannot be measured offline. Until a pilot has run, it is the size of the
example specs plus an assumed amount of thinking (OUTPUT_ASSUMPTION). After a pilot, pass its
run folder (`tokens_from`): the mean input and output tokens per architect call and the calls
per request then come from its call log (calls.jsonl), which is the measured basis for the gate.

Three numbers per run:
- expected: the calls per request (assumed, or measured) at the primary model's price;
- high: every request needs all MAX_ATTEMPTS architect calls (repairs carry the previous spec),
  with the high output assumption, at the primary model's price;
- worst: every attempt writes a reply just under max_tokens that fails the schema and needs
  the gateway's repair call (2 calls, the second carrying the first reply), and every call
  goes to the most expensive model of the chain (the fallback). Only the budget cap bounds a
  run near this.
"""

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.agents.architect import GENERATE, MAX_ATTEMPTS, REPAIR, _generate_inputs, _repair_inputs
from core.llm import load_config, load_prompt
from core.spec import SkillSpec, load_spec
from evaluation.architect.data import ArchitectItem
from evaluation.common import AI_ROOT

# Measured: E12:analyzer-dev-2026-11-24 (analysis/request v3, the 50 dev requests, live):
# 160,090 input tokens over 47 answered calls (57 calls, 10 provider errors with no tokens).
# Rendered, those prompts average 5,411 characters, plus 2,869 for the RequestAnalysis response
# schema. The answered calls include a few gateway repairs (longer), so the ratio is on the low
# side: it over-counts tokens, which keeps the estimate conservative.
# tests/agents/test_architect_estimate.py re-renders the 5,411 while the prompt is still v3.
CALIBRATION_SOURCE = "E12:analyzer-dev-2026-11-24"
CALIBRATION: dict[str, int] = {
    "input_tokens": 160_090,
    "answered_calls": 47,
    "prompt_chars": 5_411,
    "schema_chars": 2_869,
}
CHARS_PER_TOKEN = (CALIBRATION["prompt_chars"] + CALIBRATION["schema_chars"]) / (
    CALIBRATION["input_tokens"] / CALIBRATION["answered_calls"]
)
# Assumed until a pilot measures it: thinking tokens on top of the spec itself, and how many
# architect calls an average request needs (AI-05 retried 11.5% of its calls for invalid
# output; a whole spec is a longer output, so more).
OUTPUT_ASSUMPTION = {"thinking_expected": 2_000, "thinking_high": 6_000}
CALLS_PER_REQUEST_ASSUMED = 1.3
EXAMPLE_SPECS = AI_ROOT / "examples" / "skillspec"


@dataclass(frozen=True)
class Estimate:
    requests: int
    basis: str  # "assumed output" or "measured: <run folder>"
    input_tokens_per_call: float
    output_tokens_per_call: float  # expected
    output_tokens_high: float
    calls_per_request: float
    expected_usd: float
    high_usd: float
    worst_usd: float

    def lines(self) -> list[str]:
        per = 1 / self.requests if self.requests else 0.0
        return [
            f"{self.requests} requests; basis: {self.basis}",
            f"per architect call: {self.input_tokens_per_call:,.0f} input tokens, "
            f"{self.output_tokens_per_call:,.0f} output (high {self.output_tokens_high:,.0f}); "
            f"{self.calls_per_request:.2f} calls per request",
            f"expected ${self.expected_usd:.2f} (${self.expected_usd * per:.3f} per request)",
            f"high     ${self.high_usd:.2f} (${self.high_usd * per:.3f} per request: "
            f"{MAX_ATTEMPTS} attempts each)",
            f"worst    ${self.worst_usd:.2f} (${self.worst_usd * per:.3f} per request: "
            f"{MAX_ATTEMPTS} attempts x gateway repair, replies near max_tokens, fallback model)",
        ]


def schema_chars() -> int:
    from litellm.utils import type_to_response_format_param

    return len(json.dumps(type_to_response_format_param(SkillSpec)))


def spec_chars() -> float:
    """The size of a whole spec as the model writes it (the example specs, indented JSON)."""
    specs = [load_spec(p) for p in sorted(EXAMPLE_SPECS.glob("*.yaml"))]
    return statistics.mean(len(json.dumps(s.model_dump(mode="json"), indent=1)) for s in specs)


def _prices() -> tuple[dict[str, Any], dict[str, Any], int]:
    """(primary model prices, the most expensive link's prices, the role's max_tokens)."""
    config = load_config()
    role = config.role(load_prompt(GENERATE).meta.model_role)
    infos = [i for i in (config.info_for(m) for m in (role.model, *role.fallbacks)) if i]
    primary = config.info_for(role.model)
    if not primary or not infos:
        raise LookupError(f"no prices for {role.model}")
    worst = max(infos, key=lambda i: float(i["output_cost_per_token"]))
    return primary, worst, int(role.max_tokens or 0)


def _cost(info: dict[str, Any], tokens_in: float, tokens_out: float) -> float:
    return tokens_in * float(info["input_cost_per_token"]) + tokens_out * float(
        info["output_cost_per_token"]
    )


def measured_tokens(run_dir: Path) -> tuple[float, float, float]:
    """(mean input tokens, mean output tokens, architect calls per request) from a run folder's
    call log: the architect calls that returned tokens, over the requests that got a line."""
    from evaluation.architect.runlog import RunLog

    log = RunLog(run_dir, {})
    calls = [
        c
        for c in log.calls()
        if str(c.get("prompt_id", "")).startswith("architect/") and c.get("input_tokens")
    ]
    requests = len({(r["set"], r["id"]) for r in log.rows()})
    if not calls or not requests:
        raise LookupError(f"{run_dir} has no architect calls with tokens in its call log")
    return (
        statistics.mean(c["input_tokens"] for c in calls),
        statistics.mean(c.get("output_tokens") or 0 for c in calls),
        len(calls) / requests,
    )


def estimate(items: Sequence[ArchitectItem], tokens_from: Path | None = None) -> Estimate:
    primary, worst_info, max_tokens = _prices()
    schema = schema_chars()
    spec = spec_chars()
    spec_tokens = spec / CHARS_PER_TOKEN
    generate, repair = load_prompt(GENERATE), load_prompt(REPAIR)
    gen_in, rep_in = [], []
    for item in items:
        g = sum(len(m["content"]) for m in generate.render(_generate_inputs(item.analyzed, ())))
        r = sum(len(m["content"]) for m in repair.render(_repair_inputs(item.analyzed, {}, [], 2)))
        gen_in.append((g + schema) / CHARS_PER_TOKEN)
        rep_in.append((r + schema + spec) / CHARS_PER_TOKEN)  # repair carries the previous spec
    out = spec_tokens + OUTPUT_ASSUMPTION["thinking_expected"]
    out_high = spec_tokens + OUTPUT_ASSUMPTION["thinking_high"]
    calls_per_request = CALLS_PER_REQUEST_ASSUMED
    basis = f"assumed output (thinking {OUTPUT_ASSUMPTION}), input measured"
    if tokens_from is not None:
        measured_in, out, calls_per_request = measured_tokens(tokens_from)
        out_high = out * 1.5  # a request that needs repairs writes the whole spec again
        scale = measured_in / statistics.mean(gen_in) if gen_in else 1.0
        gen_in = [x * scale for x in gen_in]
        rep_in = [x * scale for x in rep_in]
        basis = f"measured from {tokens_from}"
    expected = sum(calls_per_request * _cost(primary, g, out) for g in gen_in)
    high = sum(
        _cost(primary, g, out_high) + (MAX_ATTEMPTS - 1) * _cost(primary, r, out_high)
        for g, r in zip(gen_in, rep_in, strict=True)
    )

    def attempt_worst(tokens_in: float) -> float:
        # a reply just under max_tokens that fails the schema, then the gateway's repair call,
        # which carries that reply (a reply cut off AT max_tokens skips the repair: cheaper)
        return _cost(worst_info, tokens_in, max_tokens) + _cost(
            worst_info, tokens_in + max_tokens, max_tokens
        )

    worst = sum(
        attempt_worst(g) + (MAX_ATTEMPTS - 1) * attempt_worst(r)
        for g, r in zip(gen_in, rep_in, strict=True)
    )
    n = len(items)
    return Estimate(
        requests=n,
        basis=basis,
        input_tokens_per_call=statistics.mean(gen_in) if gen_in else 0.0,
        output_tokens_per_call=out,
        output_tokens_high=out_high,
        calls_per_request=calls_per_request,
        expected_usd=round(expected, 2),
        high_usd=round(high, 2),
        worst_usd=round(worst, 2),
    )


__all__ = ["CALIBRATION", "CHARS_PER_TOKEN", "Estimate", "estimate", "measured_tokens"]
