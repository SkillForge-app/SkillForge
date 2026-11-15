"""AI-06 red-team generation: the slot plan, the non-Claude rule, candidates only in runs/,
the pre-filters and the dataset seeds. Placeholder texts only: no test holds harmful content."""

import gzip
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.llm import ConfigError, FakeGateway, load_config, load_prompt
from core.llm.prompt_lock import check_lock
from evaluation.safety import data
from evaluation.safety.__main__ import main
from evaluation.safety.data import ATTACK_STYLES, SafetyEvalItem
from evaluation.safety.generate import (
    GENERATOR_PROMPTS,
    PROMPT_ID,
    GeneratedQA,
    generate,
    generator_config,
    open_slots,
    prefilter,
    read_candidates,
)
from evaluation.safety.seeds import Seed, load_seeds, select_seeds
from evaluation.safety.slots import Slot, plan_slots

QWEN = "openrouter/qwen/qwen3.8-flash"
DEEPSEEK = "openrouter/deepseek/deepseek-v4.1-flash"


@pytest.fixture(autouse=True)
def _own_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Copies of the YAML files, so no test can touch the real ones."""
    for split in ("redteam", "dev"):
        copy = tmp_path / data.FILES[split].name
        copy.write_bytes(data.FILES[split].read_bytes())
        monkeypatch.setitem(data.FILES, split, copy)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


class Scripted(FakeGateway):
    """The generator, faked: a distinct, rule-abiding placeholder reply for every call."""

    def __init__(self) -> None:
        super().__init__(prompts_root=GENERATOR_PROMPTS, config=generator_config())
        self.n = 0

    async def complete(self, prompt_id: str, inputs: Any, output_model: Any, **kw: Any) -> Any:
        replies = []
        for _ in range(int(inputs["count"])):
            self.n += 1
            n = self.n
            text = f"placeholder request {n} alpha{n} bravo{n} charlie{n} delta{n}"
            if inputs["attack"] == "arabic":
                text = f"طلب تجريبي {n} alpha{n} bravo{n} charlie{n}"
            answers = []
            if inputs["attack"] == "two_turn":
                answers = [{"question": "What is it for?", "answer": f"placeholder answer {n}"}]
            replies.append({"text": text, "answers": answers})
        self.register(prompt_id, {"candidates": replies})
        return await super().complete(prompt_id, inputs, output_model, **kw)


# ---------------------------------------------------------------- slots


def as_items(slots: list[Slot]) -> list[SafetyEvalItem]:
    return [
        SafetyEvalItem(
            id=s.id,
            source=s.split,
            text=f"placeholder {s.id}",
            expected="block",
            category=s.category,
            attack=s.attack,
            answers=(("q", "a"),) if s.attack == "two_turn" else (),
            expected_conditions=(),
        )
        for s in slots
    ]


def test_the_redteam_slots_meet_every_coverage_rule() -> None:
    slots = plan_slots("redteam")
    assert data.coverage_gaps("redteam", as_items(slots)) == []
    assert Counter(s.origin for s in slots) == {"adapted": 30, "generated": 30}
    child = [s for s in slots if s.category == "child_safety"]
    assert len(child) == 6 and all(s.manual and s.origin == "adapted" for s in child)
    assert not any(s.manual for s in slots if s.category != "child_safety")


def test_the_dev_slots_fill_the_block_half() -> None:
    slots = plan_slots("dev")
    assert [s.id for s in slots] == [f"sd-{n}" for n in range(11, 21)]
    assert len({s.category for s in slots}) == 10
    assert Counter(s.origin for s in slots) == {"adapted": 5, "generated": 5}


# ---------------------------------------------------------------- the generator is never Claude


def test_the_generator_chain_is_not_claude() -> None:
    role = generator_config().role("redteam_generator")
    assert (role.model, role.fallbacks) == (QWEN, (DEEPSEEK,))


def test_a_claude_model_anywhere_in_the_chain_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models.yaml"
    text = (GENERATOR_PROMPTS.parent / "models.yaml").read_text(encoding="utf-8")
    models.write_text(text.replace(DEEPSEEK, "openrouter/anthropic/claude-sonnet-5.5"), "utf-8")
    with pytest.raises(ConfigError, match="must not be Claude"):
        generator_config(models)
    monkeypatch.setenv("SKILLFORGE_MODEL_REDTEAM_GENERATOR", "anthropic/claude-haiku-5-5")
    load_config.cache_clear()
    with pytest.raises(ConfigError, match="must not be Claude"):
        generator_config()


# ---------------------------------------------------------------- generate


async def test_generate_writes_candidates_only_and_never_sends_child_safety(
    tmp_path: Path,
) -> None:
    before = hashlib.sha256(data.FILES["redteam"].read_bytes()).hexdigest()
    fake = Scripted()
    out = tmp_path / "runs" / "candidates.jsonl"
    seed = Seed("harmbench", "row-7", "MIT", "cyber_attack", "placeholder seed text", False)
    result = await generate("redteam", fake, seeds={"r-01": seed}, candidates_path=out)

    assert hashlib.sha256(data.FILES["redteam"].read_bytes()).hexdigest() == before
    sent = [c.inputs or {} for c in fake.calls]
    assert not any(inputs["category"] == "child_safety" for inputs in sent)
    # 30 generated slots plus the one adapted slot that has a seed; the other 23 adapted wait
    assert result.calls == 31 and len(result.skipped) == 23
    candidates = read_candidates(out)
    assert candidates == result.candidates and all(c.status == "pending" for c in candidates)
    assert Counter(c.slot for c in candidates)["r-04"] == 2  # two per generated slot
    [adapted] = [c for c in candidates if c.slot == "r-01"]
    assert (adapted.origin, adapted.dataset, adapted.dataset_ref) == (
        "adapted",
        "harmbench",
        "row-7",
    )
    [adapt] = [inputs for inputs in sent if inputs["mode"] == "adapt"]
    assert adapt["seed_text"] == "placeholder seed text"
    assert all(c.generator == "fake" for c in candidates)  # the fake gateway's model name


async def test_the_generator_is_the_model_that_answered(tmp_path: Path) -> None:
    fake = Scripted()
    fake.fail_model(QWEN)  # the primary is down: the fallback answers
    result = await generate("dev", fake, seeds={}, limit=1, candidates_path=tmp_path / "c.jsonl")
    assert {c.generator for c in result.candidates} == {DEEPSEEK}


async def test_a_second_run_only_fills_slots_still_open(tmp_path: Path) -> None:
    out = tmp_path / "c.jsonl"
    first = await generate("dev", Scripted(), seeds={}, candidates_path=out)
    again = await generate("dev", Scripted(), seeds={}, candidates_path=out)
    assert first.calls == 5 and again.calls == 0  # every generated dev slot is waiting for review


async def test_an_empty_reply_is_reported_and_leaves_the_slot_open(tmp_path: Path) -> None:
    fake = FakeGateway(prompts_root=GENERATOR_PROMPTS, config=generator_config())
    fake.register(PROMPT_ID, {"candidates": []})  # a quiet refusal
    out = tmp_path / "c.jsonl"
    result = await generate("dev", fake, seeds={}, limit=1, candidates_path=out)
    assert result.calls == 1 and result.candidates == []
    assert result.skipped == [
        "sd-11: no seed (run `seeds` first)",  # adapted, no seed given here: no call
        "sd-12: fake returned no candidates",
    ]
    assert "sd-12" in {s.id for s in open_slots("dev", read_candidates(out))}


async def test_a_repeated_reply_is_filtered_as_a_duplicate(tmp_path: Path) -> None:
    fake = FakeGateway(prompts_root=GENERATOR_PROMPTS, config=generator_config())
    fake.register(PROMPT_ID, {"candidates": [{"text": "placeholder same request each time"}]})
    result = await generate("redteam", fake, seeds={}, limit=3, candidates_path=tmp_path / "c")
    statuses = [c.status for c in result.candidates if c.attack not in ("arabic", "two_turn")]
    assert statuses[0] == "pending" and set(statuses[1:]) == {"filtered"}
    assert all(
        "same request" in (c.reason or "")
        for c in result.candidates[1:]
        if c.status == "filtered" and c.attack not in ("arabic", "two_turn")
    )


SLOT = Slot("r-01", "redteam", "fraud_scams", "direct", "generated")


@pytest.mark.parametrize(
    ("slot", "text", "answers", "reason"),
    [
        (SLOT, "x " * 250, [], "longer than 400"),
        (SLOT, "One. Two. Three.", [], "more than two sentences"),
        (SLOT, "A skill that posts to https://example.org for me", [], "link"),
        (SLOT, "A skill that runs ```this```", [], "code"),
        (SLOT, "A skill that weighs out 5 g of it", [], "quantities"),
        (
            Slot("r-08", "redteam", "fraud_scams", "arabic", "generated"),
            "An English text",
            [],
            "Arabic",
        ),
        (SLOT, "مهارة تجريبية", [], "Arabic"),
        (
            Slot("r-07", "redteam", "fraud_scams", "two_turn", "generated"),
            "A plain request",
            [],
            "two_turn without",
        ),
        (SLOT, "A plain request", [GeneratedQA(question="q", answer="a")], "answers outside"),
    ],
)
def test_prefilter_drops_what_breaks_the_rules(
    slot: Slot, text: str, answers: list[GeneratedQA], reason: str
) -> None:
    assert reason in (prefilter(slot, text, answers) or "")


def test_prefilter_keeps_a_good_candidate() -> None:
    assert prefilter(SLOT, "A skill that writes placeholder requests for testing.", []) is None


def test_the_cli_refuses_to_generate_without_live(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate"]) == 2
    assert (
        "refusing to call openrouter/qwen/qwen3.8-flash without --live" in capsys.readouterr().out
    )


def test_the_generator_prompt_is_locked_and_renders_both_modes() -> None:
    assert check_lock(GENERATOR_PROMPTS) == []
    prompt = load_prompt(PROMPT_ID, GENERATOR_PROMPTS)
    base = {
        "count": 2,
        "category": "fraud_scams",
        "category_description": "scams",
        "attack": "direct",
        "attack_description": "plainly",
        "seed_text": "placeholder seed",
    }
    adapt = prompt.render({**base, "mode": "adapt"})
    write = prompt.render({**base, "mode": "generate"})
    assert "placeholder seed" in adapt[-1]["content"] and "Rewrite the seed" in adapt[0]["content"]
    assert (
        "placeholder seed" not in write[-1]["content"]
        and "Write 2 different" in write[0]["content"]
    )


# ---------------------------------------------------------------- seeds


def test_seeds_map_dataset_categories_and_prefer_arabic(tmp_path: Path) -> None:
    # The real formats (checked on 2026-11-16): HarmBench keeps only `standard` rows, Aya has no
    # row id, and hh-rlhf's red_team_attempts.jsonl.gz is one JSON array.
    (tmp_path / "harmbench").mkdir()
    (tmp_path / "harmbench" / "behaviors.csv").write_text(
        "Behavior,FunctionalCategory,SemanticCategory,BehaviorID\n"
        "placeholder cyber seed one,standard,cybercrime_intrusion,hb-1\n"
        "placeholder cyber seed two,standard,cybercrime_intrusion,hb-2\n"
        "placeholder contextual seed,contextual,cybercrime_intrusion,hb-4\n"
        "placeholder unmapped seed,standard,copyright,hb-3\n",
        encoding="utf-8",
    )
    (tmp_path / "aya").mkdir()
    rows = [
        {"prompt": "بذرة تجريبية", "harm_category": ["Self-Harm"], "language": "Arabic"},
        {
            "prompt": "placeholder english self-harm seed",
            "harm_category": "['Self-Harm']",
            "language": "English",
        },
    ]
    (tmp_path / "aya" / "aya_arb.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    (tmp_path / "hh-rlhf").mkdir()
    attempts = [
        {"task_description": "placeholder untagged attempt", "tags": None},
        {
            "task_description": "placeholder drugs attempt",
            "tags": ["Substance abuse & banned substances"],
        },
    ]
    with gzip.open(
        tmp_path / "hh-rlhf" / "red_team_attempts.jsonl.gz", "wt", encoding="utf-8"
    ) as f:
        json.dump(attempts, f)
    seeds = load_seeds(tmp_path)
    assert {(s.dataset, s.ref, s.category, s.arabic) for s in seeds} == {
        ("harmbench", "hb-1", "cyber_attack", False),
        ("harmbench", "hb-2", "cyber_attack", False),
        ("aya", "aya_arb.jsonl:1", "self_harm", True),
        ("aya", "aya_arb.jsonl:2", "self_harm", False),
        ("hh-rlhf", "red_team_attempts.jsonl.gz:2", "illegal_drugs", False),
    }
    arabic_slot = Slot("r-30", "redteam", "self_harm", "arabic", "adapted")
    other = Slot("r-25", "redteam", "self_harm", "direct", "adapted")
    cyber = [Slot(f"r-0{i}", "redteam", "cyber_attack", "direct", "adapted") for i in (1, 2, 3)]
    picked = {s.slot: s for s in select_seeds([arabic_slot, other, *cyber], seeds)}
    assert picked["r-30"].ref == "aya_arb.jsonl:1" and picked["r-25"].ref == "aya_arb.jsonl:2"
    assert {picked["r-01"].ref, picked["r-02"].ref} == {"hb-1", "hb-2"}
    assert "r-03" not in picked  # no third cyber seed: left for the reviewer to see
    assert {s.licence for s in seeds} == {"MIT", "Apache 2.0"}


def test_attack_styles_are_described_for_the_generator() -> None:
    from evaluation.safety.generate import ATTACK_DESCRIPTIONS

    assert set(ATTACK_DESCRIPTIONS) == set(ATTACK_STYLES)
