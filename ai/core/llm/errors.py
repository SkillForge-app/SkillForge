"""Errors raised by the LLM layer. Callers catch `LLMError` or one of its subclasses.

Messages never include prompt text, input values or model output, so they are safe to log.
"""


class LLMError(Exception):
    """Base class for every error the LLM layer raises."""


class ConfigError(LLMError):
    """Bad model configuration: unknown role, bad models.yaml, unknown backend."""


class PromptNotFound(LLMError):
    """No prompt file exists for the given prompt_id."""


class PromptFormatError(LLMError):
    """A prompt file is malformed (frontmatter, headings, or template variables)."""


class PromptLockError(LLMError):
    """prompts.lock.json cannot be updated because a prompt changed without a version bump."""


class LLMInputError(LLMError, ValueError):
    """The caller passed bad input (for example an empty text to embed)."""


class PromptInputError(LLMInputError):
    """Inputs do not match the prompt's declared inputs."""


class LLMOutputInvalid(LLMError):
    """The model output does not match the requested output model."""


class LLMRefused(LLMOutputInvalid):
    """The model (and every fallback) declined the request, e.g. a safety refusal."""


class LLMUnavailable(LLMError):
    """The provider failed: timeout, rate limit, outage, or all fallbacks exhausted."""


class BudgetExceeded(LLMError):
    """The skill run's cost budget is used up: no further model call is made (AI-21)."""
