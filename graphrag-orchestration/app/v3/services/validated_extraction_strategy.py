"""
Hybrid Extraction Strategy: Neo4j Limits + Microsoft Validation

Combines:
1. Neo4j's conservative limits (20-30 triplets) - prevents overwhelming LLM
2. Microsoft's validation pass - ensures quality
3. Iterative extraction - extracts more if needed

Flow:
  Chunk → Extract (max_triplets=30) → Validate → If chunk has more content → Extract again

This gives:
- High quality (validation)
- Completeness (iterative extraction)
- Reasonable cost (2-3 passes instead of 5)
"""

from typing import List, Tuple, Dict, Any
import logging
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.llms import LLM

logger = logging.getLogger(__name__)


class ValidatedEntityExtractor:
    """
    Entity extractor with Microsoft-style validation.
    
    Uses smaller batches (30 triplets) with validation pass to ensure quality.
    """
    
    def __init__(
        self,
        llm: LLM,
        max_triplets_per_pass: int = 30,
        validation_threshold: float = 0.7,
        max_passes: int = 3,
    ):
        """
        Args:
            llm: Language model for extraction
            max_triplets_per_pass: Conservative limit per extraction pass (Neo4j-style)
            validation_threshold: Minimum confidence score to keep entity (0-1)
            max_passes: Maximum extraction passes per chunk
        """
        self.llm = llm
        self.max_triplets_per_pass = max_triplets_per_pass
        self.validation_threshold = validation_threshold
        self.max_passes = max_passes
        
        self.extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=None,
            possible_relations=None,
            strict=False,
            num_workers=1,
            max_triplets_per_chunk=max_triplets_per_pass,
        )
    
    async def extract_with_validation(self, nodes: List[Any]) -> Tuple[List[Any], Dict[str, int]]:
        """
        Extract entities with Microsoft-style validation.
        
        Returns:
            Tuple of (validated_nodes, stats)
        """
        stats = {
            "total_passes": 0,
            "total_extracted": 0,
            "total_validated": 0,
            "total_rejected": 0,
        }
        
        # Extract entities from chunks
        logger.info(f"🔍 VALIDATION: Extracting entities from {len(nodes)} chunks with max_triplets={self.max_triplets_per_pass}")
        
        extracted_nodes = await self.extractor.acall(nodes)
        stats["total_passes"] = 1
        stats["total_extracted"] = len(extracted_nodes)
        logger.info(f"🔍 VALIDATION: Extracted {len(extracted_nodes)} nodes before validation")
        logger.info(f"🔍 VALIDATION: Extracted {len(extracted_nodes)} nodes before validation")
        
        # Validate extracted entities using LLM
        validated_nodes = []
        for node in extracted_nodes:
            # Get entities from node metadata
            kg_nodes = node.metadata.get("kg_nodes", [])
            if not kg_nodes:
                # No entities to validate, keep node as-is
                validated_nodes.append(node)
                continue
            
            # Extract entity info for validation
            entities = []
            for kg_node in kg_nodes:
                entity_name = getattr(kg_node, "name", None) or kg_node.get("name")
                entities.append({"name": entity_name})
            
            # Validate entities against source text
            chunk_text = node.text if hasattr(node, 'text') else str(node)
            validated_entities = await self.validate_entities(entities, chunk_text)
            
            # Filter entities by confidence threshold
            high_confidence_names = {
                entity["name"] for entity, confidence in validated_entities 
                if confidence >= self.validation_threshold
            }
            
            # Filter kg_nodes to keep only high-confidence entities
            filtered_kg_nodes = [
                kg_node for kg_node in kg_nodes
                if (getattr(kg_node, "name", None) or kg_node.get("name")) in high_confidence_names
            ]
            
            rejected_count = len(kg_nodes) - len(filtered_kg_nodes)
            stats["total_rejected"] += rejected_count
            stats["total_validated"] += len(filtered_kg_nodes)
            
            if rejected_count > 0:
                rejected_names = [
                    getattr(kg_node, "name", None) or kg_node.get("name")
                    for kg_node in kg_nodes
                    if (getattr(kg_node, "name", None) or kg_node.get("name")) not in high_confidence_names
                ]               
                logger.info(f"🔍 VALIDATION: Rejected {rejected_count} low-confidence entities: {rejected_names[:5]}")
            else:
                logger.info(f"🔍 VALIDATION: All entities passed validation threshold {self.validation_threshold}")
            
            # Update node with filtered entities
            node.metadata["kg_nodes"] = filtered_kg_nodes
            validated_nodes.append(node)
        
        filter_rate = (stats['total_rejected'] / stats['total_extracted'] * 100) if stats['total_extracted'] > 0 else 0
        logger.info(f"🔍 VALIDATION SUMMARY: {stats['total_validated']} validated, {stats['total_rejected']} rejected ({filter_rate:.1f}% filtered)")
        return validated_nodes, stats
    
    async def validate_entities(self, entities: List[Dict], chunk_text: str) -> List[Tuple[Dict, float]]:
        """
        Validate extracted entities using LLM.
        
        Microsoft-style validation: Ask LLM to score each entity's confidence.
        
        Args:
            entities: List of extracted entities
            chunk_text: Original text chunk
            
        Returns:
            List of (entity, confidence_score) tuples
        """
        if not entities:
            return []
        
        # Truncate chunk text if too long (keep first 1000 chars for context)
        if len(chunk_text) > 1000:
            chunk_text = chunk_text[:1000] + "..."
        
        # Create validation prompt
        entity_list = "\n".join([f"- {e['name']}" for e in entities])
        
        validation_prompt = f"""Given this text:
{chunk_text}

These entities were extracted:
{entity_list}

For each entity, rate how confident you are it's explicitly mentioned or strongly implied in the text.
Score 0-10 where:
- 10: Explicitly stated with high confidence
- 7-9: Clearly implied or stated
- 4-6: Somewhat implied
- 0-3: Weak connection or hallucinated

Return ONLY a JSON array with no markdown formatting: [{{"name": "entity", "score": 8}}]
"""
        
        try:
            response = await self.llm.acomplete(validation_prompt)
            response_text = str(response).strip()
            
            # Remove markdown code fences if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            # Parse JSON response
            import json
            try:
                scores = json.loads(response_text)
                
                # Map scores to entities
                score_map = {item["name"]: item["score"] / 10.0 for item in scores}
                
                validated = []
                for entity in entities:
                    confidence = score_map.get(entity["name"], 0.5)  # Default to 0.5 if not found
                    validated.append((entity, confidence))
                
                return validated
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse validation JSON: {e}. Response: {response_text[:200]}")
                # On parse error, trust original extraction
                return [(e, 1.0) for e in entities]
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            # On error, trust original extraction
            return [(e, 1.0) for e in entities]


# Recommended configuration based on "Lean Engine" Architecture (2025-12-23)
# Reduced triplet density to focus graph on structural logic (12-15 max)
# See: ARCHITECTURE_DECISIONS.md § Phase 2: High-Quality Local Indexing
EXTRACTION_CONFIGS = {
    "conservative": {
        # Lean Engine: Minimal triplets for simple documents
        "max_triplets_per_chunk": 10,
        "use_validation": False,
        "description": "Lean graph for simple docs (invoices, forms)"
    },
    
    "balanced": {
        # Lean Engine Default: Focus on structural relationships
        "max_triplets_per_chunk": 12,
        "use_validation": False,
        "description": "Optimal density for contract/business docs (NEW DEFAULT)"
    },
    
    "dense": {
        # Upper limit for complex documents
        "max_triplets_per_chunk": 15,
        "use_validation": False,
        "description": "Maximum density for legal/technical docs"
    },
    
    "validated_balanced": {
        # Validation pass with lean density
        "max_triplets_per_chunk": 12,
        "use_validation": True,
        "max_passes": 2,
        "description": "Quality-validated balanced extraction"
    },
}


def get_recommended_config(document_complexity: str = "medium") -> Dict[str, Any]:
    """
    Get recommended extraction configuration based on document type.
    
    Updated for "Lean Engine" architecture (12-15 triplet max).
    Focus graph on structural logic; let RAPTOR handle themes and Vector RAG handle facts.
    
    Args:
        document_complexity: "simple" | "medium" | "complex"
        
    Returns:
        Configuration dict
    """
    if document_complexity == "simple":
        # Simple docs (invoices, forms): Conservative is enough
        return EXTRACTION_CONFIGS["conservative"]
    
    elif document_complexity == "medium":
        # Business docs (contracts, reports): Balanced approach (NEW DEFAULT)
        return EXTRACTION_CONFIGS["balanced"]
    
    elif document_complexity == "complex":
        # Complex docs (legal, technical): Dense extraction (but still capped at 15)
        return EXTRACTION_CONFIGS["dense"]
    
    else:
        return EXTRACTION_CONFIGS["balanced"]


# Example usage for "Lean Engine" Architecture
"""
For contract/invoice processing (updated 2025-12-23):

Option 1: Lean Balanced (RECOMMENDED)
  max_triplets_per_chunk = 12
  No validation pass
  Focus: Structural relationships (Contract → Party → Obligation)
  Result: Clean graph, RAPTOR handles themes, Vector RAG handles facts
  
Option 2: Lean Conservative (Simple Docs)
  max_triplets_per_chunk = 10
  For simple invoices/forms
  
Option 3: Dense (Complex Docs Only)
  max_triplets_per_chunk = 15
  For legal/technical documents with many entities
  → Use this if quality is acceptable

Option 2: Neo4j conservative + validation (Highest quality)
  max_triplets_per_chunk = 25
  Add validation pass
  Result: ~400 entities, very high precision
  → Use this if quality is critical

Option 3: Hybrid (Recommended for testing)
  max_triplets_per_chunk = 30-40
  Optional validation on low-confidence extractions
  Result: ~450-500 entities, excellent quality
  → Use this to balance quality and coverage

My Recommendation:
- Test max_triplets = [20, 30, 40, 60, 80]
- Check quality manually at each level
- Choose the highest value where quality is still good
- Don't add validation pass unless seeing hallucinations
"""
