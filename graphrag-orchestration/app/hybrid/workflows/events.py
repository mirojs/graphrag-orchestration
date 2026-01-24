"""Event definitions for LlamaIndex Workflows.

Events are the communication mechanism between workflow steps.
Each event carries typed data that the next step can process.

Event Flow (DRIFT):
    StartEvent 
        → DecomposeEvent 
        → [SubQuestionEvent, SubQuestionEvent, ...] (parallel)
        → SubQuestionResultEvent (collected)
        → ConfidenceCheckEvent
        → SynthesizeEvent | ReDecomposeEvent
        → StopEvent

NOTE: LlamaIndex Events inherit from Pydantic BaseModel (via DictLikeModel).
Do NOT use @dataclass decorator - use Pydantic field definitions instead.
"""

from typing import List, Dict, Any, Optional, Tuple

from llama_index.core.workflow import Event


# =============================================================================
# DRIFT Workflow Events (Route 4)
# =============================================================================

class DecomposeEvent(Event):
    """Initial decomposition of a complex query into sub-questions."""
    query: str
    response_type: str = "detailed_report"


class SubQuestionEvent(Event):
    """A single sub-question to be processed in parallel."""
    sub_question: str
    index: int
    original_query: str


class SubQuestionResultEvent(Event):
    """Result from processing a single sub-question."""
    question: str
    entities: List[str]
    evidence: List[Any]  # List of (entity_name, score) tuples
    evidence_count: int
    index: int


class ConfidenceCheckEvent(Event):
    """Aggregated results ready for confidence evaluation."""
    results: List[Any]  # List of SubQuestionResultEvent
    original_query: str
    response_type: str


class ReDecomposeEvent(Event):
    """Trigger for re-decomposition when confidence is low."""
    refinement_prompt: str
    previous_results: List[Any]  # List of SubQuestionResultEvent
    original_query: str
    response_type: str


class SynthesizeEvent(Event):
    """Final synthesis trigger when confidence is sufficient."""
    results: List[Any]  # List of SubQuestionResultEvent
    all_seeds: List[str]
    original_query: str
    response_type: str


# =============================================================================
# Shared Events (used by multiple workflows)
# =============================================================================

class EntityDiscoveryEvent(Event):
    """Entity discovery request."""
    query: str
    max_entities: int = 10


class EvidenceRetrievedEvent(Event):
    """Evidence retrieval complete."""
    entities: List[str]
    evidence: List[Any]  # List of (entity_name, score) tuples
    source: str


# =============================================================================
# Global Search Events (Route 3) - Planned
# =============================================================================

class CommunityMatchedEvent(Event):
    """Community matching complete."""
    communities: List[Dict[str, Any]]
    query: str


class HubsExtractedEvent(Event):
    """Hub entity extraction complete."""
    hub_entities: List[str]
    query: str


class HybridRRFEvent(Event):
    """Hybrid RRF retrieval request."""
    query: str
    hub_entities: List[str]


class ChunksRetrievedEvent(Event):
    """Chunks retrieved from any retrieval stage."""
    chunks: List[Dict[str, Any]]
    source: str
    count: int = 0


class FallbackEvent(Event):
    """Fallback triggered due to error in primary path."""
    strategy: str
    error: str = ""
    context: Dict[str, Any] = {}
