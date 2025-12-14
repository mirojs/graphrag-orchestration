"""
GraphRAG Entity and Relationship Extractor.

Extracts entities and relationships from documents using LLM,
following the Microsoft GraphRAG approach.

Key difference from simple NER:
- Extracts RELATIONSHIP DESCRIPTIONS (not just labels)
- These descriptions are used for community summarization
"""

import re
import logging
import asyncio
from typing import Any, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor

from llama_index.core.schema import BaseNode, TransformComponent
from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.core.llms import ChatMessage, LLM
from llama_index.core.async_utils import run_jobs
from llama_index.core.bridge.pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Default prompt for entity/relationship extraction
DEFAULT_EXTRACT_PROMPT = """
Given a text document, identify all entities and their relationships.

For each entity, provide:
- name: The entity name
- type: The entity type (e.g., PERSON, ORGANIZATION, DOCUMENT, PRODUCT, LOCATION, DATE, AMOUNT)
- description: A brief description of the entity

For each relationship, provide:
- source: The source entity name
- target: The target entity name  
- relationship: The relationship type (e.g., MENTIONS, CONTAINS, PART_OF, RELATED_TO, AUTHORED_BY)
- description: A detailed description of how these entities are related

Output format (JSON):
{{
  "entities": [
    {{"name": "...", "type": "...", "description": "..."}}
  ],
  "relationships": [
    {{"source": "...", "target": "...", "relationship": "...", "description": "..."}}
  ]
}}

Text to analyze:
{text}

Extract entities and relationships:
"""


class EntityRelationship(BaseModel):
    """A single entity-relationship-entity triple with descriptions."""
    source_entity: str = Field(description="Source entity name")
    source_type: str = Field(description="Source entity type")
    target_entity: str = Field(description="Target entity name")
    target_type: str = Field(description="Target entity type")
    relationship: str = Field(description="Relationship type/label")
    relationship_description: str = Field(description="Detailed description of the relationship")


class GraphRAGExtractor(TransformComponent):
    """
    Extract entities and relationships from documents for GraphRAG.
    
    This extractor:
    1. Uses LLM to identify entities and relationships
    2. Extracts DETAILED relationship descriptions (key for GraphRAG)
    3. Outputs EntityNode and Relation objects for the property graph
    4. Generates embeddings for entities (for vector-based retrieval)
    
    Speed Considerations:
    - One LLM call per document chunk
    - Can be parallelized with num_workers
    - Consider batching small documents
    """
    
    def __init__(
        self,
        llm: Optional[Any] = None,
        embed_model: Optional[Any] = None,
        extract_prompt: Optional[str] = None,
        max_paths_per_chunk: int = 20,
        num_workers: int = 4,
        group_id: str = "",
        generate_embeddings: bool = True,
    ):
        """
        Initialize the extractor.
        
        Args:
            llm: LLM instance for extraction
            embed_model: Embedding model for entity embeddings
            extract_prompt: Custom prompt template (must include {text})
            max_paths_per_chunk: Maximum entity-relationship paths per chunk
            num_workers: Parallel workers for async extraction
            group_id: Multi-tenancy group ID
            generate_embeddings: Whether to generate embeddings for entities
        """
        self._llm = llm
        self._embed_model = embed_model
        self.extract_prompt = extract_prompt or DEFAULT_EXTRACT_PROMPT
        self.max_paths_per_chunk = max_paths_per_chunk
        self.num_workers = num_workers
        self.group_id = group_id
        self.generate_embeddings = generate_embeddings
    
    @property
    def llm(self) -> LLM:
        """Lazy load LLM."""
        if self._llm is None:
            from app.services.llm_service import LLMService
            self._llm = LLMService().llm
        assert self._llm is not None, "LLM service failed to initialize"
        return self._llm
    
    @property
    def embed_model(self):
        """Lazy load embedding model."""
        if self._embed_model is None:
            from app.services.llm_service import LLMService
            self._embed_model = LLMService().embed_model
        return self._embed_model
    
    def __call__(
        self, 
        nodes: List[BaseNode], 
        show_progress: bool = False,
        **kwargs
    ) -> List[BaseNode]:
        """
        Synchronous extraction for compatibility.
        """
        return asyncio.run(self.acall(nodes, show_progress=show_progress, **kwargs))
    
    async def acall(
        self, 
        nodes: List[BaseNode], 
        show_progress: bool = False,
        **kwargs
    ) -> List[BaseNode]:
        """
        Extract entities and relationships from nodes asynchronously.
        
        Returns:
            Original nodes plus extracted EntityNode and Relation objects
        """
        jobs = []
        for node in nodes:
            jobs.append(self._aextract(node))
        
        results = await run_jobs(
            jobs,
            workers=self.num_workers,
            show_progress=show_progress,
            desc="Extracting entities and relationships",
        )
        
        # Flatten results and combine with original nodes
        all_nodes = list(nodes)  # Keep original document nodes
        for entity_nodes, relations in results:
            all_nodes.extend(entity_nodes)
            # Relations are stored separately via the graph store
        
        return all_nodes
    
    async def _aextract(
        self, 
        node: BaseNode
    ) -> Tuple[List[EntityNode], List[Relation]]:
        """
        Extract entities and relationships from a single node.
        """
        text = node.get_content()
        
        if not text or len(text.strip()) < 10:
            return [], []
        
        # Call LLM for extraction
        prompt = self.extract_prompt.format(text=text)
        
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = await asyncio.to_thread(self.llm.chat, messages)
            response_text = str(response).strip()
            
            # Parse the JSON response
            entities, relationships = self._parse_extraction_response(response_text)
            
            # Convert to EntityNode and Relation objects
            entity_nodes = self._create_entity_nodes(entities, node.node_id)
            relations = self._create_relations(relationships, node.node_id)
            
            logger.info(f"Extracted {len(entity_nodes)} entities and {len(relations)} relations from node {node.node_id}")
            
            return entity_nodes, relations
            
        except Exception as e:
            logger.error(f"Extraction failed for node {node.node_id}: {e}")
            return [], []
    
    def _parse_extraction_response(
        self, 
        response_text: str
    ) -> Tuple[List[dict], List[dict]]:
        """
        Parse LLM response to extract entities and relationships.
        """
        import json
        
        # Try to find JSON in the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if not json_match:
            logger.warning("No JSON found in extraction response")
            return [], []
        
        try:
            data = json.loads(json_match.group())
            entities = data.get("entities", [])
            relationships = data.get("relationships", [])
            return entities, relationships
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")
            return [], []
    
    def _create_entity_nodes(
        self, 
        entities: List[dict], 
        source_chunk_id: str
    ) -> List[EntityNode]:
        """
        Create EntityNode objects from extracted entities with embeddings.
        """
        entity_nodes = []
        entity_names = []
        filtered_entities = []
        
        for entity in entities[:self.max_paths_per_chunk]:
            name = entity.get("name", "").strip()
            if not name:
                continue
            entity_names.append(name)
            filtered_entities.append(entity)
        
        # Generate embeddings in batch if enabled
        embeddings = []
        if self.generate_embeddings and entity_names:
            try:
                logger.info(f"Generating embeddings for {len(entity_names)} entities...")
                embeddings = self.embed_model.get_text_embedding_batch(entity_names)
                logger.info(f"Generated {len(embeddings)} embeddings")
            except Exception as e:
                logger.warning(f"Failed to generate embeddings: {e}")
                embeddings = [None] * len(entity_names)
        else:
            embeddings = [None] * len(entity_names)
        
        # Create EntityNodes with embeddings
        for entity, embedding in zip(filtered_entities, embeddings):
            name = entity.get("name", "").strip()
            entity_node = EntityNode(
                name=name,
                label=entity.get("type", "ENTITY"),
                properties={
                    "description": entity.get("description", ""),
                    "group_id": self.group_id,
                    "triplet_source_id": source_chunk_id,
                }
            )
            if embedding is not None:
                entity_node.embedding = embedding
            entity_nodes.append(entity_node)
        
        return entity_nodes
    
    def _create_relations(
        self, 
        relationships: List[dict], 
        source_chunk_id: str
    ) -> List[Relation]:
        """
        Create Relation objects from extracted relationships.
        
        Key: Includes relationship_description for GraphRAG community summaries.
        """
        relations = []
        
        for rel in relationships[:self.max_paths_per_chunk]:
            source = rel.get("source", "").strip()
            target = rel.get("target", "").strip()
            
            if not source or not target:
                continue
            
            relation = Relation(
                source_id=source,
                target_id=target,
                label=rel.get("relationship", "RELATED_TO"),
                properties={
                    "relationship_description": rel.get("description", ""),
                    "group_id": self.group_id,
                    "triplet_source_id": source_chunk_id,
                }
            )
            relations.append(relation)

            # Infer role/title from the relationship description and emit a structured edge.
            role_title = self._extract_role_title(rel)
            if role_title:
                relations.append(
                    Relation(
                        source_id=source,
                        target_id=target,
                        label="HAS_ROLE",
                        properties={
                            "title": role_title,
                            "group_id": self.group_id,
                            "triplet_source_id": source_chunk_id,
                            "inferred_from": "relationship_description",
                        },
                    )
                )
        
        return relations

    def _extract_role_title(self, rel: dict) -> Optional[str]:
        """
        Heuristic extractor for job titles in the relationship description.
        This is a lightweight, rule-based fallback to enrich the graph with
        role semantics without relying on the MENTIONS edge.
        """
        description = rel.get("description", "") or ""
        label = rel.get("relationship", "") or ""
        text = f"{label} {description}".lower()
        role_patterns = [
            r"\bceo\b",
            r"\bcto\b",
            r"\bcfo\b",
            r"\bcoo\b",
            r"chief [a-z ]+",
            r"\bvp\b",
            r"vice president",
            r"head of [a-z ]+",
            r"director",
            r"manager",
            r"lead",
            r"engineer",
            r"founder",
            r"co[- ]founder",
            r"owner",
            r"president",
            r"chair(wo)?man",
            r"board member",
        ]
        for pattern in role_patterns:
            match = re.search(pattern, text)
            if match:
                title = match.group(0).strip()
                return title.title()
        return None
    
    def extract_from_text(self, text: str, source_id: str = "manual") -> Tuple[List[EntityNode], List[Relation]]:
        """
        Synchronous helper for extracting from raw text.
        
        Useful for testing or single-document extraction.
        """
        from llama_index.core.schema import TextNode
        
        node = TextNode(text=text, id_=source_id)
        
        # Run extraction synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            entity_nodes, relations = loop.run_until_complete(self._aextract(node))
            return entity_nodes, relations
        finally:
            loop.close()


class SimpleGraphRAGExtractor:
    """
    Simpler synchronous extractor for smaller workloads.
    
    Use this for:
    - Testing
    - Small document sets
    - When you don't need async parallelism
    
    Now includes embedding generation for vector-based entity retrieval.
    """
    
    def __init__(
        self,
        llm: Optional[Any] = None,
        embed_model: Optional[Any] = None,
        group_id: str = "",
        generate_embeddings: bool = True,
    ):
        self._llm = llm
        self._embed_model = embed_model
        self.group_id = group_id
        self.generate_embeddings = generate_embeddings
    
    @property
    def llm(self) -> LLM:
        if self._llm is None:
            from app.services.llm_service import LLMService
            self._llm = LLMService().llm
        assert self._llm is not None, "LLM service failed to initialize"
        return self._llm
    
    @property
    def embed_model(self):
        """Lazy load embedding model."""
        if self._embed_model is None:
            from app.services.llm_service import LLMService
            self._embed_model = LLMService().embed_model
        return self._embed_model
    
    def extract(self, text: str, source_id: str = "manual") -> Tuple[List[EntityNode], List[Relation]]:
        """
        Extract entities and relationships from text.
        
        Now includes embedding generation for vector-based entity retrieval.
        
        Returns:
            Tuple of (entity_nodes, relations)
        """
        prompt = f"""
Analyze this text and extract:
1. All entities (people, organizations, documents, locations, amounts, dates)
2. All relationships between entities

Output as JSON:
{{
  "entities": [{{"name": "...", "type": "...", "description": "..."}}],
  "relationships": [{{"source": "...", "target": "...", "relationship": "...", "description": "..."}}]
}}

Text:
{text}
"""
        
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = self.llm.chat(messages)
            response_text = str(response).strip()
            
            # Parse JSON
            import json
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                return [], []
            
            data = json.loads(json_match.group())
            
            # Create EntityNodes with embeddings
            entity_nodes = []
            entity_names = []
            entity_data = []
            
            for e in data.get("entities", []):
                if e.get("name"):
                    entity_names.append(e["name"])
                    entity_data.append(e)
            
            # Generate embeddings in batch if enabled
            embeddings = []
            if self.generate_embeddings and entity_names:
                try:
                    logger.info(f"Generating embeddings for {len(entity_names)} entities...")
                    # Use batch embedding for efficiency
                    embeddings = self.embed_model.get_text_embedding_batch(entity_names)
                    logger.info(f"Generated {len(embeddings)} embeddings")
                except Exception as e:
                    logger.warning(f"Failed to generate embeddings: {e}")
                    embeddings = [None] * len(entity_names)
            else:
                embeddings = [None] * len(entity_names)
            
            # Create EntityNodes with embeddings
            for i, (e, embedding) in enumerate(zip(entity_data, embeddings)):
                entity_node = EntityNode(
                    name=e["name"],
                    label=e.get("type", "ENTITY"),
                    properties={
                        "description": e.get("description", ""),
                        "group_id": self.group_id,
                        "triplet_source_id": source_id,
                    }
                )
                if embedding is not None:
                    entity_node.embedding = embedding
                entity_nodes.append(entity_node)
            
            # Create Relations
            relations = []
            for r in data.get("relationships", []):
                if r.get("source") and r.get("target"):
                    relations.append(Relation(
                        source_id=r["source"],
                        target_id=r["target"],
                        label=r.get("relationship", "RELATED_TO"),
                        properties={
                            "relationship_description": r.get("description", ""),
                            "group_id": self.group_id,
                            "triplet_source_id": source_id,
                        }
                    ))
            
            logger.info(f"Extracted {len(entity_nodes)} entities (with embeddings: {sum(1 for e in entity_nodes if e.embedding is not None)}) and {len(relations)} relations")
            return entity_nodes, relations
            
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return [], []

    def extract_batch(
        self, 
        texts: List[str], 
        source_ids: Optional[List[str]] = None,
        max_concurrent: int = 10,
        show_progress: bool = True
    ) -> Tuple[List[EntityNode], List[Relation]]:
        """
        Extract entities and relationships from multiple texts in parallel.
        
        Uses asyncio for concurrent LLM calls, optimized for higher rate limits.
        
        Args:
            texts: List of text documents to process
            source_ids: Optional list of source IDs (defaults to doc-0, doc-1, etc.)
            max_concurrent: Maximum concurrent LLM requests (increase with higher rate limits)
            show_progress: Whether to show progress bar
            
        Returns:
            Tuple of (all_entities, all_relations) combined from all documents
        """
        if source_ids is None:
            source_ids = [f"doc-{i}" for i in range(len(texts))]
        
        async def _extract_all():
            import asyncio
            from tqdm.asyncio import tqdm_asyncio
            
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def _extract_one(text: str, source_id: str) -> Tuple[List[EntityNode], List[Relation]]:
                async with semaphore:
                    # Run sync extraction in thread pool
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None, 
                        self.extract, 
                        text, 
                        source_id
                    )
            
            tasks = [
                _extract_one(text, sid) 
                for text, sid in zip(texts, source_ids)
            ]
            
            if show_progress:
                results = await tqdm_asyncio.gather(*tasks, desc="Extracting entities")
            else:
                results = await asyncio.gather(*tasks)
            
            return results
        
        # Run async extraction
        results = asyncio.run(_extract_all())
        
        # Combine all results
        all_entities = []
        all_relations = []
        for entities, relations in results:
            all_entities.extend(entities)
            all_relations.extend(relations)
        
        logger.info(f"Batch extraction complete: {len(all_entities)} entities, {len(all_relations)} relations from {len(texts)} documents")
        return all_entities, all_relations

