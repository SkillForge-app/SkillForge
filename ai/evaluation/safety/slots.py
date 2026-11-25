"""The slot plan for the block items still to write (AI-06): one slot per item id, each with
its category, attack style and origin, so the finished files meet LABELLING.md's coverage.

    redteam: r-01 .. r-60   6 per category; 24 adapted, 30 generated, 6 verbatim
    dev:     sd-11 .. sd-20 1 per category (not `other`); 4 adapted, 5 generated, 1 verbatim

child_safety slots are `verbatim`: a SimpleSafetyTests row used as it is, by reference
(`python -m evaluation.safety verbatim`). No model generates or rewords them and no person
writes them. Those rows are plain requests, so their slots are all `direct`:

    redteam style counts: direct 13, euphemism 7, fiction_wrapper 7, education_wrapper 7,
    authority_claim 7, prompt_injection 7, two_turn 6, arabic 6 (every minimum of 3 still holds)
"""

from dataclasses import dataclass
from typing import Literal

from core.analysis.types import HARM_CATEGORIES, HarmCategory
from evaluation.safety.data import ATTACK_STYLES, VERBATIM_CATEGORY, AttackStyle

Split = Literal["redteam", "dev"]
SlotOrigin = Literal["generated", "adapted", "verbatim"]
CATEGORIES: tuple[HarmCategory, ...] = tuple(c for c in HARM_CATEGORIES if c != "other")
PER_CATEGORY = 6
# Adapted slots per red-team category, in CATEGORIES order without child_safety (its 6 slots
# are verbatim): 6 x 3 + 3 x 2 = 24, plus child_safety's 6 = 30 of 60 from datasets.
ADAPTED_PER_CATEGORY = (3, 3, 3, 3, 3, 3, 2, 2, 2)
# The dev block half: 4 adapted, child_safety verbatim, the other 5 generated.
DEV_ADAPTED = frozenset({"cyber_attack", "weapons", "self_harm", "hate_extremism"})


@dataclass(frozen=True)
class Slot:
    id: str  # the item id it fills
    split: Split
    category: HarmCategory
    attack: AttackStyle
    origin: SlotOrigin

    @property
    def verbatim(self) -> bool:
        """A dataset row by reference; never sent to the generator, never written by a person."""
        return self.origin == "verbatim"


def plan_slots(split: Split) -> list[Slot]:
    return _redteam() if split == "redteam" else _dev()


def _redteam() -> list[Slot]:
    slots = []
    adapted = iter(ADAPTED_PER_CATEGORY)
    for ci, category in enumerate(CATEGORIES):
        n_adapted = 0 if category == VERBATIM_CATEGORY else next(adapted)
        for j in range(PER_CATEGORY):
            k = ci * PER_CATEGORY + j
            slot_id = f"r-{k + 1:02d}"
            if category == VERBATIM_CATEGORY:
                slots.append(Slot(slot_id, "redteam", category, "direct", "verbatim"))
                continue
            origin: SlotOrigin = "adapted" if j < n_adapted else "generated"
            slots.append(Slot(slot_id, "redteam", category, ATTACK_STYLES[k % 8], origin))
    return slots


def _dev() -> list[Slot]:
    slots = []
    for i, category in enumerate(CATEGORIES):
        origin: SlotOrigin = (
            "verbatim"
            if category == VERBATIM_CATEGORY
            else "adapted"
            if category in DEV_ADAPTED
            else "generated"
        )
        attack: AttackStyle = "direct" if origin == "verbatim" else ATTACK_STYLES[(i + 3) % 8]
        slots.append(Slot(f"sd-{i + 11}", "dev", category, attack, origin))
    return slots
