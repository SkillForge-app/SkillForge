"""The architect cost estimate (AI-07 pre-flight): measured input, then measured from a pilot."""

import json
import statistics
from pathlib import Path

import pytest
from litellm.utils import type_to_response_format_param

from core.analysis import PROMPT_ID, RequestAnalysis
from core.analysis.request import _inputs
from core.llm import load_config, load_prompt
from evaluation.analyzer.data import load_set
from evaluation.architect.__main__ import main
from evaluation.architect.data import load_items
from evaluation.architect.estimate import CALIBRATION, CHARS_PER_TOKEN, estimate, measured_tokens
from evaluation.architect.runlog import CALLS, PREDICTIONS


@pytest.mark.skipif(
    load_prompt(PROMPT_ID).version != 3, reason="the calibration was measured on analysis v3"
)
def test_calibration_characters_are_what_the_measured_run_sent() -> None:
    prompt = load_prompt(PROMPT_ID)
    chars = [
        sum(len(m["content"]) for m in prompt.render(_inputs(i.text, ()))) for i in load_set("dev")
    ]
    assert len(chars) == 50  # the 50 dev requests of the E12 run
    assert round(statistics.mean(chars)) == CALIBRATION["prompt_chars"]
    assert (
        len(json.dumps(type_to_response_format_param(RequestAnalysis)))
        == CALIBRATION["schema_chars"]
    )
    assert 2.0 < CHARS_PER_TOKEN < 4.0


def test_expected_high_worst_are_ordered_and_priced_from_models_yaml() -> None:
    est = estimate(load_items("all"))
    assert est.requests == 103
    assert 0 < est.expected_usd < est.high_usd < est.worst_usd
    config = load_config()
    role = config.role("architect")
    prices = [config.info_for(m) for m in (role.model, *role.fallbacks)]
    assert all(p is not None for p in prices[:2])  # the OpenRouter links are priced
    # the worst case is priced at the most expensive link (the Opus fallback)
    assert est.worst_usd > 2 * est.high_usd


def write_pilot(run: Path, calls: list[dict[str, object]], requests: int) -> None:
    run.mkdir(parents=True)
    (run / CALLS).write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    rows = [{"set": "dev", "id": f"dev:d-{n:02}"} for n in range(requests)]
    (run / PREDICTIONS).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_a_pilot_call_log_replaces_the_assumptions(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = [
        {"prompt_id": "architect/generate", "input_tokens": 7000, "output_tokens": 3000},
        {"prompt_id": "architect/generate", "input_tokens": 7000, "output_tokens": 5000},
        {"prompt_id": "architect/repair", "input_tokens": 10000, "output_tokens": 4000},
        {"prompt_id": "architect/generate", "status": "error"},  # no tokens: not counted
        {"prompt_id": "analysis/request", "input_tokens": 3000, "output_tokens": 200},
    ]
    write_pilot(tmp_path / "pilot", calls, requests=2)
    assert measured_tokens(tmp_path / "pilot") == (8000, 4000, 1.5)
    est = estimate(load_items("dev")[:2], tokens_from=tmp_path / "pilot")
    assert est.output_tokens_per_call == 4000 and est.calls_per_request == 1.5
    assert est.input_tokens_per_call == pytest.approx(8000)
    assert "measured" in est.basis


def test_no_call_log_no_measured_estimate(tmp_path: Path) -> None:
    write_pilot(tmp_path / "pilot", [], requests=1)
    with pytest.raises(LookupError):
        measured_tokens(tmp_path / "pilot")


def test_cli_estimate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["estimate", "--set", "dev", "--ids", "d-02,d-03"]) == 0
    out = capsys.readouterr().out
    assert "2 requests" in out and "expected $" in out and "worst" in out
