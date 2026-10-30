"""Helpers shared by the evaluation tools (analyzer, safety, ...)."""

import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from dotenv import load_dotenv

from core.llm import load_config, load_prompt
from core.llm.config import key_env_for
from core.llm.gateway import BACKEND_ENV

I = TypeVar("I")  # noqa: E741
R = TypeVar("R")

AI_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Outcome(Generic[I, R]):
    item: I
    result: R | None
    error: str | None  # exception class name; any failure counts as a wrong answer
    latency_ms: float


async def run_all(
    items: Sequence[I], fn: Callable[[I], Awaitable[R]], *, concurrency: int = 4
) -> list[Outcome[I, R]]:
    """Run `fn` on every item, at most `concurrency` at a time. Errors are recorded, not raised."""
    gate = asyncio.Semaphore(concurrency)

    async def one(item: I) -> Outcome[I, R]:
        async with gate:
            start = time.perf_counter()
            try:
                result: R | None = await fn(item)
                error = None
            except Exception as exc:
                result, error = None, type(exc).__name__
            return Outcome(item, result, error, (time.perf_counter() - start) * 1000)

    return list(await asyncio.gather(*(one(i) for i in items)))


def model_for(prompt_id: str) -> str:
    return load_config().role(load_prompt(prompt_id).meta.model_role).model


def live_guard(live: bool, prompt_id: str) -> int | None:
    """Refuse real (paid) model calls unless --live is given and the provider key is set.

    Returns an exit code when the run must stop, or None when it may go ahead.
    """
    backend = os.environ.get(BACKEND_ENV, "litellm").strip().lower()
    if not live:
        if backend != "fake":
            print(
                "refusing to call a real model without --live (it costs money). "
                f"For a smoke test set {BACKEND_ENV}=fake.",
                file=sys.stderr,
            )
            return 2
        return None
    if backend == "fake":
        print(f"--live cannot be used with {BACKEND_ENV}=fake", file=sys.stderr)
        return 2
    load_dotenv(AI_ROOT / ".env", override=False)
    model = model_for(prompt_id)
    key = key_env_for(model)
    if key and not os.environ.get(key):
        print(f"--live needs {key} for {model} (env var or ai/.env)", file=sys.stderr)
        return 2
    return None


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; (0, 1) when there is nothing to measure."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def write_new_files(out_dir: Path, stem: str, contents: dict[str, str]) -> tuple[Path, ...]:
    """Write one report's files ({suffix: text}) under a name no earlier report uses.

    The name is `<stem>`, else `<stem>-2`, `<stem>-3`, ...: a file a person has reviewed is
    never overwritten. Files are created exclusively, so even two runs at once cannot clash.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        name = stem if n == 1 else f"{stem}-{n}"
        paths = tuple(out_dir / f"{name}{suffix}" for suffix in contents)
        if not any(p.exists() for p in paths):
            try:
                for path, text in zip(paths, contents.values(), strict=True):
                    with path.open("x", encoding="utf-8", newline="\n") as f:
                        f.write(text)
                return paths
            except FileExistsError:
                pass  # another run took this name between the check and the write
        n += 1
