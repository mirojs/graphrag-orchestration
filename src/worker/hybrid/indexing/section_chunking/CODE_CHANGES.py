"""
Code Changes Required for Section-Aware Chunking Integration

This file contains the exact code snippets to add/modify in existing files.
Apply these changes in order.

=============================================================================
STEP 1: lazygraphrag_pipeline.py - Add imports and feature flag
=============================================================================
"""

# Location: After existing imports (~line 50)
# Add these lines:

STEP_1_IMPORTS = '''
# Section-aware chunking feature flag (Trial - January 2026)
USE_SECTION_CHUNKING = os.getenv("USE_SECTION_CHUNKING", "1").strip().lower() in {"1", "true", "yes"}
'''

"""
=============================================================================
STEP 2: lazygraphrag_pipeline.py - Modify _chunk_di_units method
=============================================================================
"""

# Location: Start of _chunk_di_units method (~line 315)
# Replace the method signature and first few lines with:

STEP_2_CHUNK_DI_UNITS = '''
    async def _chunk_di_units(self, *, di_units: Sequence[LlamaDocument], doc_id: str) -> List[TextChunk]:
        """Chunk DI-extracted document units.
        
        Uses section-aware chunking when USE_SECTION_CHUNKING=1, otherwise
        falls back to fixed-size chunking.
        """
        # Check if section-aware chunking is enabled
        if USE_SECTION_CHUNKING:
            return await self._chunk_di_units_section_aware(di_units=di_units, doc_id=doc_id)
        
        # Original fixed-size chunking logic follows...
        chunks: List[TextChunk] = []
        chunk_index = 0
        # ... (rest of existing method unchanged)
'''

"""
=============================================================================
STEP 3: lazygraphrag_pipeline.py - Add new section-aware method
=============================================================================
"""

# Location: After _chunk_di_units method (~line 375)
# Add this new method:

STEP_3_NEW_METHOD = '''
    async def _chunk_di_units_section_aware(
        self, 
        *, 
        di_units: Sequence[LlamaDocument], 
        doc_id: str
    ) -> List[TextChunk]:
        """Section-aware chunking using Azure DI section boundaries.
        
        This method creates chunks aligned with document structure (H1, H2, etc.)
        instead of fixed token windows. Benefits:
        - Coherent embeddings (one topic per chunk)
        - Summary section detection (for coverage retrieval)
        - Structural metadata preservation
        
        Requires: Documents extracted with Azure DI prebuilt-layout model.
        """
        from src.worker.hybrid.indexing.section_chunking.integration import (
            chunk_di_units_section_aware
        )
        
        # Extract doc metadata for the chunker
        doc_source = ""
        doc_title = ""
        if di_units:
            first_meta = getattr(di_units[0], "metadata", None) or {}
            doc_source = first_meta.get("url", "") or first_meta.get("source", "")
            doc_title = first_meta.get("title", "")
        
        logger.info(
            "section_aware_chunking_start",
            doc_id=doc_id,
            num_di_units=len(di_units),
        )
        
        text_chunks = await chunk_di_units_section_aware(
            di_units=di_units,
            doc_id=doc_id,
            doc_source=doc_source,
            doc_title=doc_title,
        )
        
        logger.info(
            "section_aware_chunking_complete",
            doc_id=doc_id,
            num_chunks=len(text_chunks),
            summary_chunks=sum(1 for c in text_chunks if (c.metadata or {}).get("is_summary_section")),
        )
        
        return text_chunks
'''

"""
=============================================================================
STEP 4: enhanced_graph_retriever.py - Add summary section retrieval
=============================================================================
"""

# Location: After get_coverage_chunks method (~line 1770)
# Add this new method:

STEP_4_SUMMARY_RETRIEVAL = '''
    async def get_summary_chunks_by_section(
        self,
        max_per_document: int = 1,
    ) -> List[SourceChunk]:
        """Get summary section chunks for coverage-guaranteed queries.
        
        This method leverages section-aware chunking metadata to retrieve
        semantically appropriate chunks (Purpose, Introduction sections)
        instead of arbitrary first chunks.
        
        Requires: Documents indexed with USE_SECTION_CHUNKING=1
        
        Falls back to chunk_index=0 if no summary sections found (backward compatible).
        """
        if not self.driver:
            return []
        
        # Query prefers is_summary_section=true, falls back to chunk_index=0
        query = """
        MATCH (d:Document)<-[:PART_OF]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
        WITH d, t,
             CASE 
                 WHEN t.metadata IS NOT NULL 
                      AND apoc.convert.fromJsonMap(t.metadata).is_summary_section = true 
                 THEN 0
                 WHEN t.chunk_index = 0 THEN 1
                 ELSE 2
             END AS priority
        ORDER BY d.id, priority, t.chunk_index ASC
        WITH d, collect(t)[0..$max_per_document] AS chunks
        UNWIND chunks AS chunk
        OPTIONAL MATCH (chunk)-[:IN_SECTION]->(s:Section)
        RETURN
            chunk.id AS chunk_id,
            chunk.text AS text,
            chunk.metadata AS metadata,
            chunk.chunk_index AS chunk_index,
            s.id AS section_id,
            s.path_key AS section_path_key,
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        max_per_document=max_per_document,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            chunks: List[SourceChunk] = []
            docs_seen: set = set()
            
            for record in records:
                doc_id = (record.get("doc_id") or "").strip()
                if doc_id in docs_seen:
                    continue
                docs_seen.add(doc_id)
                
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}
                
                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key and not section_path:
                    section_path = section_path_key.split(" > ")
                
                chunks.append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name="summary_section_retrieval",
                        section_path=section_path,
                        section_id=record.get("section_id") or metadata.get("section_id", ""),
                        document_id=doc_id,
                        document_title=record.get("doc_title") or "",
                        document_source=record.get("doc_source") or "",
                        relevance_score=1.0,
                    )
                )
            
            logger.info(
                "summary_section_chunks_retrieved",
                num_chunks=len(chunks),
                num_docs=len(docs_seen),
                group_id=self.group_id,
            )
            return chunks
            
        except Exception as e:
            logger.error("summary_section_retrieval_failed", error=str(e))
            return []
'''

"""
=============================================================================
STEP 5: orchestrator.py - Update coverage retrieval to prefer summary sections
=============================================================================
"""

# Location: Stage 3.4.1 coverage gap fill (~line 3020)
# Replace the coverage_chunks retrieval line with:

STEP_5_COVERAGE_UPDATE = '''
                # Try summary section retrieval first (requires section-aware indexing)
                # Falls back to position-based retrieval if no summary sections
                use_section_retrieval = os.getenv("USE_SECTION_RETRIEVAL", "1").strip().lower() in {"1", "true", "yes"}
                
                if use_section_retrieval:
                    coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(
                        max_per_document=1,
                    )
                    if coverage_chunks:
                        logger.info("stage_3.4.1_using_summary_sections", chunks=len(coverage_chunks))
                    else:
                        logger.info("stage_3.4.1_fallback_to_position_based")
                        coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(
                            max_per_document=1,
                            max_total=20,
                        )
                else:
                    coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(
                        max_per_document=1,
                        max_total=20,
                    )
'''

"""
=============================================================================
VERIFICATION QUERIES (Neo4j)
=============================================================================
"""

VERIFY_SECTION_CHUNKING = '''
-- Verify chunks have section metadata
MATCH (c:TextChunk {group_id: $group_id})
WHERE c.metadata IS NOT NULL
WITH c, apoc.convert.fromJsonMap(c.metadata) AS meta
RETURN 
    c.document_id,
    meta.section_title,
    meta.section_level,
    meta.is_summary_section,
    meta.chunk_strategy,
    count(*) as chunk_count
ORDER BY c.document_id
LIMIT 50;

-- Find summary sections
MATCH (c:TextChunk {group_id: $group_id})
WHERE c.metadata IS NOT NULL
WITH c, apoc.convert.fromJsonMap(c.metadata) AS meta
WHERE meta.is_summary_section = true
RETURN 
    c.document_id,
    meta.section_title,
    substring(c.text, 0, 200) as preview
ORDER BY c.document_id;

-- Compare chunk counts: section vs fixed
MATCH (c:TextChunk {group_id: $group_id})
WHERE c.metadata IS NOT NULL
WITH c, apoc.convert.fromJsonMap(c.metadata) AS meta
RETURN 
    coalesce(meta.chunk_strategy, 'fixed') as strategy,
    count(*) as chunks,
    avg(size(c.text)) as avg_text_length
GROUP BY strategy;
'''

if __name__ == "__main__":
    print("This file contains code snippets for manual integration.")
    print("See INTEGRATION_PLAN.md for step-by-step instructions.")
    print()
    print("Code changes required:")
    print("  1. lazygraphrag_pipeline.py - Add USE_SECTION_CHUNKING flag")
    print("  2. lazygraphrag_pipeline.py - Modify _chunk_di_units")
    print("  3. lazygraphrag_pipeline.py - Add _chunk_di_units_section_aware")
    print("  4. enhanced_graph_retriever.py - Add get_summary_chunks_by_section")
    print("  5. orchestrator.py - Update coverage retrieval")
