"""SkillForge core pipeline."""

import os

# LiteLLM downloads its price map from GitHub `main` when it is imported, unless this is set.
# Set it here, so any `import core...` comes first; a process that imports litellm before core
# must set it itself (see docs/ai/models-and-gateway.md).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
