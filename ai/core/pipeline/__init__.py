"""The AI pipeline interface (contract for BE-07 and BE-08): what the backend worker calls.

    from core.pipeline import RealPipeline, FakePipeline, StepResult

See docs/ai/pipeline-interface.md.
"""

from core.pipeline.fake import FakePipeline, example_request, example_spec
from core.pipeline.interface import (
    PIPELINE_VERSION,
    AIPipeline,
    IssueRecord,
    ProgressEvent,
    RealPipeline,
    StepName,
    StepResult,
    StepStatus,
    Usage,
)

__all__ = [
    "PIPELINE_VERSION",
    "AIPipeline",
    "FakePipeline",
    "IssueRecord",
    "ProgressEvent",
    "RealPipeline",
    "StepName",
    "StepResult",
    "StepStatus",
    "Usage",
    "example_request",
    "example_spec",
]
