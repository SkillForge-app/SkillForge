"""The environment for code from a recorded commit (AI-25): `run` re-runs and twins.render_at.

Code at an old commit is not trusted with this machine's secrets or its network: it could read
OPENROUTER_API_KEY and make a paid, live call. So it gets:

- an ALLOWLISTED environment only: PATH, SYSTEMROOT, TEMP/TMP, HOME/USERPROFILE, LANG, and the
  settings set here. Every other variable (any *_KEY, *_TOKEN, *_SECRET, DATABASE_URL, ...) is
  dropped, whatever its name;
- no way out over HTTP: HTTP_PROXY / HTTPS_PROXY / ALL_PROXY point at 127.0.0.1:0 and
  NO_PROXY is empty, so httpx, requests and urllib (which LiteLLM and the hub client use) fail;
  HF_HUB_OFFLINE=1;
- the entry's own backend: SKILLFORGE_LLM_BACKEND=fake unless the entry says local-model (then the
  real gateway with SKILLFORGE_MODEL_CACHE, and no key to call anything with);
- and it refuses an extracted tree that holds an ai/.env (the gateway would load keys from it).

A raw socket ignores proxies: the OS-level block (a network namespace) stays a follow-up.
"""

import os
from collections.abc import Mapping
from pathlib import Path

ALLOWED = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")
# Port 0 can't be connected to: the attempt fails at once on Windows and Linux (a closed
# port such as 9 takes ~2 s per attempt on Windows, which made E2 run for hours).
DEAD_PROXY = "http://127.0.0.1:0"
PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


class UnsafeTree(RuntimeError):
    """An extracted tree that must not be run (it holds an .env)."""


def sandbox_env(
    *, model_cache: Path | None = None, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The whole environment for an old commit's code. `model_cache`: the entry runs on the local
    model (its files there); None: the fake backend. `extra`: e.g. PYTHONPATH for render_at."""
    env = {name: os.environ[name] for name in ALLOWED if name in os.environ}
    env.update(
        PYTHONHASHSEED="0",
        PYTHONUTF8="1",
        HF_HUB_OFFLINE="1",
        SKILLFORGE_SEARCH="fake",
        NO_PROXY="",
    )
    for name in PROXIES:
        env[name] = DEAD_PROXY
    if os.name != "nt":  # Windows variables are case-insensitive: one spelling is enough there
        env.update({name.lower(): DEAD_PROXY for name in PROXIES}, no_proxy="")
    if model_cache is None:
        env["SKILLFORGE_LLM_BACKEND"] = "fake"
    else:
        env["SKILLFORGE_MODEL_CACHE"] = str(model_cache)
    env.update(extra or {})
    return env


def refuse_env_file(tree: Path) -> None:
    """`tree` is an extracted ai/ folder: it must not hold an .env (never committed so far)."""
    if (tree / ".env").exists():
        raise UnsafeTree(f"{tree / '.env'} exists in the extracted tree: refusing to run it")


__all__ = ["ALLOWED", "DEAD_PROXY", "UnsafeTree", "refuse_env_file", "sandbox_env"]
