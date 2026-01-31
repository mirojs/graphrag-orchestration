"""
Structured Output Service for Schema-Guided Retrieval.

This service implements the PRIMARY use case for schemas: extracting structured
data from the Knowledge Graph at RETRIEVAL time (query time), not indexing time.

Architecture:
1. User provides a JSON schema (e.g., {"vendor": str, "amount": float, "date": str})
2. GraphRAG retrieves relevant context from Neo4j (Vector + Graph traversal)
3. LLM extracts structured data from context, outputting JSON matching the schema
4. Response is validated against the schema

This is similar to Azure Content Understanding, but uses the local Knowledge Graph
instead of raw documents.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, create_model
import jsonschema

from llama_index.core.llms import LLM
from llama_index.core.schema import NodeWithScore

logger = logging.getLogger(__name__)


class ExtractionResult(BaseModel):
    """Result of schema-guided extraction."""
    query: str
    schema_name: Optional[str] = None
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StructuredOutputService:
    """
    Service for extracting structured data from Knowledge Graph using JSON schemas.
    
    This is the PRIMARY schema use case: query-time structured extraction.
    
    Flow:
    1. Receive query + output_schema
    2. Use GraphRAG to retrieve relevant nodes/context
    3. Pass context + schema to LLM for structured extraction
    4. Validate output against schema
    5. Return structured JSON
    """
    
    def __init__(self, llm: LLM):
        self.llm = llm
        
    def _generate_extraction_prompt(
        self,
        query: str,
        context: str,
        schema: Dict[str, Any],
        schema_name: Optional[str] = None
    ) -> str:
        """
        Generate a prompt for schema-guided extraction.
        
        The prompt instructs the LLM to:
        1. Analyze the retrieved context
        2. Extract fields defined in the schema
        3. Output valid JSON matching the schema structure
        """
        # Format schema for the prompt
        schema_description = self._format_schema_for_prompt(schema)
        
        prompt = f"""You are a precise data extraction assistant. Your task is to extract structured data from the provided context.

## Query
{query}

## Target Schema{f" ({schema_name})" if schema_name else ""}
Extract data matching this JSON schema structure:

{schema_description}

## Retrieved Context
{context}

## Instructions
1. Carefully read the context above
2. Extract values for each field defined in the schema
3. Use null for fields where information is not available in the context
4. For arrays, include all matching items found
5. For nested objects, extract all sub-fields
6. Maintain exact field names as specified in the schema
7. Output ONLY valid JSON - no explanations, no markdown code blocks

## Output
Return a JSON object with the extracted data:
"""
        return prompt
    
    def _format_schema_for_prompt(self, schema: Dict[str, Any]) -> str:
        """
        Format a JSON schema for inclusion in the prompt.
        
        Includes field names, types, descriptions, and nested structure.
        """
        lines = []
        
        # Handle root level
        if "properties" in schema:
            lines.append("```json")
            lines.append("{")
            
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            defs = schema.get("$defs", {})
            
            for i, (field_name, field_info) in enumerate(properties.items()):
                is_required = field_name in required
                field_desc = self._describe_field(field_name, field_info, defs, indent=2)
                lines.append(field_desc + ("," if i < len(properties) - 1 else ""))
            
            lines.append("}")
            lines.append("```")
            
            # Add field descriptions
            lines.append("\n**Field Descriptions:**")
            for field_name, field_info in properties.items():
                desc = field_info.get("description", "")
                field_type = field_info.get("type", "any")
                is_required = "required" if field_name in required else "optional"
                if desc:
                    lines.append(f"- `{field_name}` ({field_type}, {is_required}): {desc}")
                else:
                    lines.append(f"- `{field_name}` ({field_type}, {is_required})")
        else:
            # Simple schema without properties
            lines.append("```json")
            lines.append(json.dumps(schema, indent=2))
            lines.append("```")
        
        return "\n".join(lines)
    
    def _describe_field(
        self, 
        name: str, 
        info: Dict[str, Any], 
        defs: Dict[str, Any],
        indent: int = 0
    ) -> str:
        """Describe a single field for the prompt."""
        spaces = " " * indent
        field_type = info.get("type", "any")
        
        if field_type == "array":
            items = info.get("items", {})
            if "$ref" in items:
                ref_name = items["$ref"].split("/")[-1]
                return f'{spaces}"{name}": [<{ref_name} objects>]'
            return f'{spaces}"{name}": [<{items.get("type", "any")} items>]'
        
        elif field_type == "object":
            return f'{spaces}"{name}": {{<nested object>}}'
        
        elif "$ref" in info:
            ref_name = info["$ref"].split("/")[-1]
            return f'{spaces}"{name}": <{ref_name} object>'
        
        else:
            # Primitive type with example
            examples = {
                "string": '"..."',
                "number": "0.0",
                "integer": "0",
                "boolean": "true/false",
            }
            example = examples.get(field_type, "null")
            return f'{spaces}"{name}": {example}'
    
    async def extract_structured(
        self,
        query: str,
        retrieved_nodes: List[NodeWithScore],
        output_schema: Dict[str, Any],
        schema_name: Optional[str] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from retrieved nodes using the output schema.
        
        Args:
            query: The user's natural language query
            retrieved_nodes: Nodes retrieved from GraphRAG
            output_schema: JSON schema defining the expected output structure
            schema_name: Optional name for the schema (for logging/debugging)
            
        Returns:
            ExtractionResult with extracted data and metadata
        """
        logger.info(f"Structured extraction: query='{query[:50]}...', schema={schema_name or 'unnamed'}")
        
        # Build context from retrieved nodes
        context = self._build_context_from_nodes(retrieved_nodes)
        
        if not context.strip():
            logger.warning("No context retrieved for structured extraction")
            return ExtractionResult(
                query=query,
                schema_name=schema_name,
                extracted_data={},
                confidence=0.0,
                sources=[],
                validation_errors=["No relevant context found in the knowledge graph"],
                metadata={"node_count": 0}
            )
        
        # Generate extraction prompt
        prompt = self._generate_extraction_prompt(query, context, output_schema, schema_name)
        
        # Call LLM for extraction
        try:
            response = await self.llm.acomplete(prompt)
            raw_output = str(response).strip()
            
            # Clean up response (remove markdown code blocks if present)
            raw_output = self._clean_json_output(raw_output)
            
            # Parse JSON
            try:
                extracted_data = json.loads(raw_output)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM output as JSON: {e}")
                logger.error(f"Raw output: {raw_output[:500]}")
                return ExtractionResult(
                    query=query,
                    schema_name=schema_name,
                    extracted_data={},
                    confidence=0.0,
                    sources=self._extract_sources(retrieved_nodes),
                    validation_errors=[f"Invalid JSON output: {str(e)}"],
                    metadata={"raw_output": raw_output[:500]}
                )
            
            # Validate against schema
            validation_errors = self._validate_against_schema(extracted_data, output_schema)
            
            # Calculate confidence based on completeness
            confidence = self._calculate_confidence(extracted_data, output_schema)
            
            return ExtractionResult(
                query=query,
                schema_name=schema_name,
                extracted_data=extracted_data,
                confidence=confidence,
                sources=self._extract_sources(retrieved_nodes),
                validation_errors=validation_errors,
                metadata={
                    "node_count": len(retrieved_nodes),
                    "context_length": len(context),
                    "schema_fields": len(output_schema.get("properties", {})),
                }
            )
            
        except Exception as e:
            logger.error(f"Structured extraction failed: {e}", exc_info=True)
            return ExtractionResult(
                query=query,
                schema_name=schema_name,
                extracted_data={},
                confidence=0.0,
                sources=[],
                validation_errors=[f"Extraction failed: {str(e)}"],
                metadata={}
            )
    
    def _build_context_from_nodes(self, nodes: List[NodeWithScore]) -> str:
        """Build context string from retrieved nodes."""
        context_parts = []
        
        for i, node_with_score in enumerate(nodes, 1):
            node = node_with_score.node
            # Use get_content() which is the standard LlamaIndex method for node text
            text = node.get_content() if hasattr(node, 'get_content') else str(node)
            score = node_with_score.score
            
            # Get metadata
            metadata = node.metadata if hasattr(node, 'metadata') else {}
            source = metadata.get('source', 'unknown')
            name = metadata.get('name', '')
            
            # Format context entry
            header = f"[Source {i}] (relevance: {score:.2f})"
            if name:
                header += f" - {name}"
            
            context_parts.append(f"{header}\n{text}")
        
        return "\n\n---\n\n".join(context_parts)
    
    def _clean_json_output(self, output: str) -> str:
        """Remove markdown code blocks and other artifacts from LLM output."""
        # Remove ```json ... ``` blocks
        if "```json" in output:
            start = output.find("```json") + 7
            end = output.find("```", start)
            if end > start:
                output = output[start:end].strip()
        elif "```" in output:
            start = output.find("```") + 3
            end = output.find("```", start)
            if end > start:
                output = output[start:end].strip()
        
        # Remove leading/trailing whitespace
        output = output.strip()
        
        return output
    
    def _validate_against_schema(
        self, 
        data: Dict[str, Any], 
        schema: Dict[str, Any]
    ) -> List[str]:
        """Validate extracted data against the JSON schema."""
        errors = []
        
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation error: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"Invalid schema: {e.message}")
        
        return errors
    
    def _calculate_confidence(
        self, 
        data: Dict[str, Any], 
        schema: Dict[str, Any]
    ) -> float:
        """
        Calculate extraction confidence based on completeness.
        
        Confidence is based on:
        - Percentage of required fields that are not null
        - Percentage of optional fields that are not null (weighted less)
        """
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        
        if not properties:
            return 1.0 if data else 0.0
        
        required_filled = 0
        required_total = len(required)
        optional_filled = 0
        optional_total = len(properties) - required_total
        
        for field_name, field_info in properties.items():
            value = data.get(field_name)
            is_filled = value is not None and value != "" and value != []
            
            if field_name in required:
                if is_filled:
                    required_filled += 1
            else:
                if is_filled:
                    optional_filled += 1
        
        # Weight: 70% for required fields, 30% for optional
        required_score = (required_filled / required_total) if required_total > 0 else 1.0
        optional_score = (optional_filled / optional_total) if optional_total > 0 else 1.0
        
        confidence = 0.7 * required_score + 0.3 * optional_score
        return round(confidence, 2)
    
    def _extract_sources(self, nodes: List[NodeWithScore]) -> List[Dict[str, Any]]:
        """Extract source information from nodes for provenance."""
        sources = []
        
        for node_with_score in nodes:
            node = node_with_score.node
            metadata = node.metadata if hasattr(node, 'metadata') else {}
            
            sources.append({
                "id": node.id_ if hasattr(node, 'id_') else str(id(node)),
                "score": node_with_score.score,
                "source_type": metadata.get("source", "unknown"),
                "entity_name": metadata.get("name", ""),
                "label": metadata.get("label", ""),
            })
        
        return sources[:10]  # Limit to top 10 sources
