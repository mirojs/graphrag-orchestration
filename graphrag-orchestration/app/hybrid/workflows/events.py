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
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from llama_index.core.workflow import Event


# =============================================================================
# DRIFT Workflow Events (Route 4)
# =============================================================================

@dataclass
class DecomposeEvent(Event):
    """Initial decomposition of a complex query into sub-questions.
    
    Attributes:
        query: The original user query
        response_type: Desired response format (e.g., "detailed_report")
    """
    query: str
    response_type: str = "detailed_report"


@dataclass  
class SubQuestionEvent(Event):
    """A single sub-question to be processed in parallel.
    
    Attributes:
        sub_question: The decomposed sub-question text
        index: Position in the original list (for ordering results)
        original_query: The parent query for context
    """
    sub_question: str
    index: int
    original_query: str


@dataclass
class SubQuestionResultEvent(Event):
    """Result from processing a single sub-question.
    
    Attributes:
        question: The sub-question that was processed
        entities: Disambiguated entities found
        evidence: Evidence retrieved from graph/PPR tracing
        evidence_count: Number of evidence items
        index: Position for ordering
    """
    question: str
    entities: List[str]
    evidence: List[Tuple[str, float]]  # (entity_name, score)
    evidence_count: int
    index: int


@dataclass
class ConfidenceCheckEvent(Event):
    """Aggregated results ready for confidence evaluation.
    
    Attributes:
        results: All sub-question results collected
        original_query: The parent query
        response_type: Desired response format
    """
    results: List[SubQuestionResultEvent]
    original_query: str
    response_type: str


@dataclass
class ReDecomposeEvent(Event):
    """Trigger for re-decomposition when confidence is low.
    
    Attributes:
        refinement_prompt: Prompt for generating better sub-questions
        previous_results: Results from first pass (for context)
        original_query: The parent query
        response_type: Desired response format
    """
    refinement_prompt: str
    previous_results: List[SubQuestionResultEvent]
    original_query: str
    response_type: str


@dataclass
class SynthesizeEvent(Event):
    """Final synthesis trigger when confidence is sufficient.
    
    Attributes:
        results: All sub-question results
        all_seeds: Deduplicated entity seeds for final PPR
        original_query: The parent query
        response_type: Desired response format
    """
    results: List[SubQuestionResultEvent]
    all_seeds: List[str]
    original_query: str
    response_type: str


# =============================================================================
# Shared Events (used by multiple workflows)
# =============================================================================

@dataclass
class EntityDiscoveryEvent(Event):
    """Entity discovery request.
    
    Attributes:
        query: Query to find entities for
        max_entities: Maximum entities to return
    """
    query: str
    max_entities: int = 10


@dataclass
class EvidenceRetrievedEvent(Event):
    """Evidence retrieval complete.
    
    Attributes:
        entities: Entities used for retrieval
        evidence: Retrieved evidence with scores
        source: Source of evidence (e.g., "ppr", "bm25", "vector")
    """
    entities: List[str]
    evidence: List[Tuple[str, float]]
    source: str


# =============================================================================
# Global Search Events (Route 3) - Planned
# =============================================================================

@dataclass
class CommunityMatchedEvent(Event):
    """Community matching complete.
    
    Attributes:
        communities: Matched community data
        query: The original query
    """
    communities: List[Dict[str, Any]]
    query: str


@dataclass
class HubsExtractedEvent(Event):
    """Hub entity extraction complete.
    
    Attributes:
        hub_entities: Extracted hub entities
        query: The original query
    """
    hub_entities: List[str]
    query: str


@dataclass
class HybridRRFEvent(Event):
    """Hybrid RRF retrieval request.
    
    Attributes:
        query: Search query
        hub_entities: Seed entities for context
    """
    query: str
    hub_entities: List[str]


@dataclass
class ChunksRetrievedEvent(Event):
    """Chunks retrieved from any retrieval stage.
    
    Attributes:
        chunks: Retrieved text chunks
        source: Retrieval source (e.g., "hybrid_rrf", "bm25", "vector")
        count: Number of chunks
    """
    chunks: List[Dict[str, Any]]
    source: str
    count: int = field(default=0)
    
    def __post_init__(self):
        if self.count == 0:
            self.count = len(self.chunks)


@dataclass
class FallbackEvent(Event):
    """Fallback triggered due to error in primary path.
    
    Attributes:
        strategy: Fallback strategy to use
        error: Error message from primary path
        context: Additional context for fallback
    """
    strategy: str
    error: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
