"""SkillForge LLM layer (Track A): the gateway, prompt files, model roles and usage logging.

Track B and other callers import from here only. See docs/ai/models-and-gateway.md.
"""

from core.llm.config import ModelConfig, ModelRole, load_config
from core.llm.errors import (
    BudgetExceeded,
    ConfigError,
    DeadlineExceeded,
    LLMError,
    LLMInputError,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
    PromptFormatError,
    PromptInputError,
    PromptNotFound,
)
from core.llm.fake import FakeGateway, FakeOutputMissing, use_fake
from core.llm.gateway import (
    LLMGateway,
    complete,
    complete_sync,
    embed,
    embed_sync,
    get_gateway,
    set_gateway,
)
from core.llm.limits import Limits, RoleLimit, get_limits, set_limits, step_deadline
from core.llm.prompts import Prompt, load_prompt
from core.llm.usage import (
    CallRecord,
    SkillRun,
    UsageTotals,
    check_budget,
    current_skill_run,
    skill_run,
    track_usage,
)

__all__ = [
    "BudgetExceeded",
    "CallRecord",
    "ConfigError",
    "DeadlineExceeded",
    "FakeGateway",
    "FakeOutputMissing",
    "LLMError",
    "LLMGateway",
    "LLMInputError",
    "LLMOutputInvalid",
    "LLMRefused",
    "LLMUnavailable",
    "Limits",
    "ModelConfig",
    "ModelRole",
    "Prompt",
    "PromptFormatError",
    "PromptInputError",
    "PromptNotFound",
    "RoleLimit",
    "SkillRun",
    "UsageTotals",
    "check_budget",
    "current_skill_run",
    "complete",
    "complete_sync",
    "embed",
    "embed_sync",
    "get_gateway",
    "get_limits",
    "load_config",
    "load_prompt",
    "set_gateway",
    "set_limits",
    "skill_run",
    "step_deadline",
    "track_usage",
    "use_fake",
]
