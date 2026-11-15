"""The slot plan for the block items still to write (AI-06): one slot per item id, each with
its category, attack style and origin, so the finished files meet LABELLING.md's coverage.

    redteam: r-01 .. r-60   6 per category, 7 or 8 per attack style, 30 adapted, 30 generated
    dev:     sd-11 .. sd-20 1 per category (not `other`), 5 adapted, 5 generated

child_safety is adapted by hand only: its slots are `manual`, and no model ever sees them.
"""

from dataclasses import dataclass
from typing import Literal

from core.analysis.types import HARM_CATEGORIES, HarmCategory
from evaluation.safety.data import ATTACK_STYLES, AttackStyle

Split = Literal["redteam", "dev"]
CATEGORIES: tuple[HarmCategory, ...] = tuple(c for c in HARM_CATEGORIES if c != "other")
MANUAL_CATEGORY: HarmCategory = "child_safety"
PER_CATEGORY = 6
# Adapted slots per red-team category, in CATEGORIES order without child_safety (all 6 of its
# slots are adapted): 6 x 3 + 3 x 2 = 24, plus child_safety's 6 = 30 of 60.
ADAPTED_PER_CATEGORY = (3, 3, 3, 3, 3, 3, 2, 2, 2)
# The dev block half: 5 adapted (child_safety among them), the other 5 generated.
DEV_ADAPTED = frozenset({"cyber_attack", "weapons", "self_harm", "hate_extremism", "child_safety"})


@dataclass(frozen=True)
class Slot:
    id: str  # the item id it fills
    split: Split
    category: HarmCategory
    attack: AttackStyle
    origin: Literal["generated", "adapted"]

    @property
    def manual(self) -> bool:
        """Written by the reviewer from a dataset seed; never sent to the generator."""
        return self.category == MANUAL_CATEGORY


def plan_slots(split: Split) -> list[Slot]:
    return _redteam() if split == "redteam" else _dev()


def _redteam() -> list[Slot]:
    slots = []
    adapted = iter(ADAPTED_PER_CATEGORY)
    for ci, category in enumerate(CATEGORIES):
        n_adapted = PER_CATEGORY if category == MANUAL_CATEGORY else next(adapted)
        for j in range(PER_CATEGORY):
            k = ci * PER_CATEGORY + j
            origin: Literal["generated", "adapted"] = "adapted" if j < n_adapted else "generated"
            slots.append(Slot(f"r-{k + 1:02d}", "redteam", category, ATTACK_STYLES[k % 8], origin))
    return slots


def _dev() -> list[Slot]:
    slots = []
    for i, category in enumerate(CATEGORIES):
        origin: Literal["generated", "adapted"] = (
            "adapted" if category in DEV_ADAPTED else "generated"
        )
        slots.append(Slot(f"sd-{i + 11}", "dev", category, ATTACK_STYLES[(i + 3) % 8], origin))
    return slots
