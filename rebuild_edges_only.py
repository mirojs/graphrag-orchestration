#!/usr/bin/env python3
"""
Rebuild only the SEMANTICALLY_SIMILAR edges using the deployed pipeline with new threshold.
"""
import asyncio
from app.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGPipeline
from app.core.config import settings

GROUP_ID = "test-5pdfs-1768486622652179443"

async def main():
    print(f"🔗 Rebuilding SEMANTICALLY_SIMILAR edges for: {GROUP_ID}")
    print(f"   New similarity threshold: 0.43 (was 0.80)")
    print()
    
    # Initialize the pipeline
    pipeline = LazyGraphRAGPipeline()
    
    # Call only the edge-building method
    print("Step 1: Building section similarity edges...")
    result = await pipeline._build_section_similarity_edges(GROUP_ID)
    
    print(f"\n✅ Complete!")
    print(f"   Edges created: {result.get('edges_created', 0)}")
    print(f"   Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
