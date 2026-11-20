"""The worker's model check, and the placeholder worker until Backend's worker exists (OPS).

    python /app/devops/worker_check.py          # check, then wait (the compose `worker` service)
    python /app/devops/worker_check.py --once   # check and exit 0, or exit 1 (CI, smoke tests)

1. The pinned embedding model must already be in SKILLFORGE_MODEL_CACHE (the `models` volume,
   written only by the model-init service). Nothing is ever downloaded here: a missing or
   corrupt model exits 1 with a message that says how to fix it.
2. The model is loaded and embeds one sentence, through the same gateway call the pipeline
   uses (core.llm.embed_sync), with HF_HUB_OFFLINE=1 and no network needed.

When Backend's worker lands, the service runs `rq worker ... skills` instead; this check can stay
as a startup step before it.
"""

import argparse
import math
import os
import signal
import sys

ROLE = "embedding"


def check() -> str:
    from core.llm import ConfigError, embed_sync, load_config
    from core.llm.local_embed import ensure_model

    role = load_config().role(ROLE)
    if role.local is None:
        raise SystemExit(f"worker: role {ROLE!r} is not a local model ({role.model})")
    try:
        folder = ensure_model(role.local, download=False)  # never downloads
    except ConfigError as exc:
        cache = os.environ.get("SKILLFORGE_MODEL_CACHE", "(SKILLFORGE_MODEL_CACHE not set)")
        print(
            f"worker: the embedding model is not ready in {cache}: {exc}. In compose, the "
            "model-init service downloads it into the `models` volume "
            "(docker compose --profile worker run --rm model-init).",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    [vector] = embed_sync(["worker model check"], model_role=ROLE)
    if len(vector) != (role.dimensions or len(vector)) or not all(map(math.isfinite, vector)):
        raise SystemExit(f"worker: the model gave a bad vector ({len(vector)} values)")
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    return (
        f"worker placeholder: model ok ({role.model}, {len(vector)} dims, "
        f"{'offline' if offline else 'HF_HUB_OFFLINE not set'}) from {folder}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="worker_check.py")
    parser.add_argument("--once", action="store_true", help="check and exit (no waiting)")
    args = parser.parse_args()
    print(check(), flush=True)
    if args.once:
        return 0
    print(
        "worker placeholder: waiting; Backend's worker (rq worker ... skills) replaces this",
        flush=True,
    )
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        signal.pause()


if __name__ == "__main__":
    sys.exit(main())
