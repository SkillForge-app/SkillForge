# Installing AI's code (the `skillforge` package) from `data/`

Only needed to run the `ai_real` tests or the real adapter (`skillforge_data/adapters/ai.py`). The default install and the default CI do not need it.

**NEVER run `pip install skillforge`, and never add `skillforge` as a dependency or extra of `data/`.** That name on PyPI is not our package
(dependency confusion). For the same reason `pyproject.toml` has no `ai` extra and no `[tool.uv.sources]`, and `data/uv.lock` must not be added
(`devops/ci/run-project.sh` would then run `uv sync --locked --all-extras`).

Python 3.11.5 or newer (`requires-python`, same as `ai/`). Run from `data/`, in this order:

```
pip install -e ".[dev]"
(cd ../ai && uv export --locked --no-emit-project --format requirements-txt -o <temp folder on E:>/ai-req.txt)
pip install -r <the same file>
pip install --no-deps -e ../ai
pip check
```

- The second line exports AI's pinned, hashed dependencies from `ai/uv.lock` (spaCy, fastembed, `en-core-web-sm` from its GitHub URL...). The third installs
  exactly those. The fourth installs AI's own package from the path without resolving anything. `pip check` must report no broken requirements.
- On Windows use Git Bash for the subshell, or run the two parts separately in PowerShell. Use a temporary folder instead of `/tmp`; keep caches and
  the temp file on E: (C: is small).
- Run the tests: `pytest -m ai_real -rs`. The default `pytest -q -rs` still deselects them.

## Model and network

- CI does not download the embedding model. `ai_real` tests use AI's `use_fake()` gateway, so they never download it either.
- In staging and production DevOps preloads the model (about 66 MB) in a volume mounted at `SKILLFORGE_MODEL_CACHE`, with `HF_HUB_OFFLINE=1`.
  DevOps will add an optional CI job for `ai_real` on the same closed network.
