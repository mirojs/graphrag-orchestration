"""LlamaIndex Workflows for Route 3 & 4 parallel execution.

This module provides workflow implementations that enable:
- Parallel execution of independent stages
- Structured fallback handling via events
- Automatic observability via LlamaIndex instrumentation
- Clean event-driven confidence loops

Available Workflows:
- DRIFTWorkflow: Route 4 multi-hop reasoning with parallel sub-question processing
- GlobalSearchWorkflow: Route 3 thematic search (planned)

Usage:
    from src.worker.hybrid_v2.workflows import DRIFTWorkflow
    
    workflow = DRIFTWorkflow(pipeline=pipeline, timeout=60)
    result = await workflow.run(query="What are the payment terms across all agreements?")
"""

from .events import (
    # DRIFT Events
    DecomposeEvent,
    SubQuestionEvent,
    SubQuestionResultEvent,
    ConfidenceCheckEvent,
    ReDecomposeEvent,
    SynthesizeEvent,
    # Shared Events
    EntityDiscoveryEvent,
    EvidenceRetrievedEvent,
)

from .drift_workflow import DRIFTWorkflow

__all__ = [
    # Workflows
    "DRIFTWorkflow",
    # Events
    "DecomposeEvent",
    "SubQuestionEvent",
    "SubQuestionResultEvent",
    "ConfidenceCheckEvent",
    "ReDecomposeEvent",
    "SynthesizeEvent",
    "EntityDiscoveryEvent",
    "EvidenceRetrievedEvent",
]
