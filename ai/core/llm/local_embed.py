"""Local embedding models (AI-11): pinned ONNX files from Hugging Face, run with fastembed.

An embedding role whose model is `local/<name>` runs in-process on CPU: no API key, no
per-call cost, no torch. Its files are pinned in models.yaml (repo, commit, model file and its
sha256), downloaded once into SKILLFORGE_MODEL_CACHE (default ai/.data/models) and checked
before every load. fastembed is only ever given that local folder, so it never downloads.

    python -m core.llm.local_embed download              # the `embedding` role's model
    python -m core.llm.local_embed download --role NAME  # another local role
"""

import argparse
import hashlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.llm.config import LOCAL_PREFIX, LocalModel, load_config
from core.llm.errors import ConfigError

CACHE_ENV = "SKILLFORGE_MODEL_CACHE"
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / ".data" / "models"
_SUPPORT_FILES = ["*.json", "*.txt"]  # tokenizer and config files next to the model


def cache_root() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE)


def model_dir(local: LocalModel) -> Path:
    return cache_root() / local.repo.replace("/", "--") / local.revision[:12]


def ensure_model(local: LocalModel, *, download: bool = True) -> Path:
    """The folder holding the pinned model, downloading it first if needed. Raises ConfigError
    when the file is missing (and `download` is off) or does not match its sha256."""
    folder = model_dir(local)
    target = folder / local.file
    if not target.is_file():
        if not download:
            raise ConfigError(
                f"{local.repo} is not downloaded; run `python -m core.llm.local_embed download`"
            )
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=local.repo,
            revision=local.revision,
            local_dir=folder,
            allow_patterns=[local.file, *_SUPPORT_FILES],
        )
    digest = _sha256(target)
    if digest != local.sha256:
        raise ConfigError(
            f"{local.repo}/{local.file} has sha256 {digest[:12]}…, not the pinned "
            f"{local.sha256[:12]}…; delete {folder} and download again"
        )
    return folder


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=4)
def _load(name: str, local: LocalModel) -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(name, specific_model_path=str(ensure_model(local)))


def embed_local(model: str, local: LocalModel, texts: list[str]) -> list[list[float]]:
    """Unit-length vectors for `texts`, in order. Blocking: call it from a worker thread."""
    embedder = _load(model.removeprefix(LOCAL_PREFIX), local)
    return [vector.tolist() for vector in embedder.embed(texts, batch_size=32)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.llm.local_embed")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="fetch and check a local model's files")
    download.add_argument("--role", default="embedding", help="model role (default: embedding)")
    args = parser.parse_args(argv)
    role = load_config().role(args.role)
    if role.local is None:
        print(f"role {args.role!r} uses {role.model}, not a local model", file=sys.stderr)
        return 2
    folder = ensure_model(role.local)
    print(f"{role.model}: {folder} (sha256 ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
