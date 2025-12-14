import asyncio
import os
import traceback
import logging
import sys
from typing import List, Set, Literal, Optional, Union, get_args
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor, SimpleLLMPathExtractor
from llama_index.core.schema import TextNode
from llama_index.llms.azure_openai import AzureOpenAI
from app.core.config import settings

# Enable verbose logging to see LLM interactions
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

async def main():
    print("=" * 60)
    print("DEBUG: Dynamic Literal type creation (like in pipeline)")
    print("=" * 60)
    
    print("\nInitializing LLM...")
    llm = AzureOpenAI(
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )

    text = """
    Apple Inc. reported record quarterly revenue. 
    Tim Cook, the CEO, announced the new iPhone 15 at the event in Cupertino.
    The device costs $999.
    The board meeting happened on September 12, 2023.
    Google is a competitor located in Mountain View.
    """
    
    nodes = [TextNode(text=text)]

    # Simulate what the pipeline does: dynamic lists from config
    entity_types_list = ["ORGANIZATION", "PERSON", "LOCATION", "PRODUCT", "EVENT", "DATE"]
    relation_types_list = ["WORKS_AT", "LOCATED_IN", "OWNS", "MANUFACTURES", "ANNOUNCED", "COMPETES_WITH", "HAPPENED_ON"]
    
    # KEY FIX: Create Literal types dynamically from lists!
    # This is what we now do in the pipeline
    EntityTypeLiteral = Literal[tuple(entity_types_list)]  # type: ignore
    RelationTypeLiteral = Literal[tuple(relation_types_list)]  # type: ignore
    
    print(f"\n--- TEST CONFIGURATION ---")
    print(f"Entity Types (list): {entity_types_list}")
    print(f"Relation Types (list): {relation_types_list}")
    print(f"EntityTypeLiteral: {EntityTypeLiteral}")
    print(f"strict=True with DYNAMIC Literal types")
    
    try:
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=EntityTypeLiteral,
            possible_relations=RelationTypeLiteral,
            kg_validation_schema=None,
            strict=True,
            num_workers=1,
            max_triplets_per_chunk=10,
        )
        print("\n✅ Extractor initialized successfully with dynamic Literal types!")
        
        print("\nCalling extractor...")
        results = await extractor.acall(nodes)
        
        print(f"\n--- EXTRACTION RESULTS ---")
        print(f"Total Extracted Items: {len(results)}")
        
        for i, node in enumerate(results):
            print(f"\nNode {i}:")
            print(f"  All metadata keys: {list(node.metadata.keys())}")
            
            # Check BOTH possible key names
            kg_nodes = node.metadata.get("kg_nodes", node.metadata.get("nodes", []))
            kg_relations = node.metadata.get("kg_relations", node.metadata.get("relations", []))
            
            print(f"\n  Entities found: {len(kg_nodes)}")
            for n in kg_nodes[:10]:
                print(f"    - {n}")
            
            print(f"\n  Relations found: {len(kg_relations)}")
            for r in kg_relations[:10]:
                print(f"    - {r}")
        
        print("\n✅ SUCCESS: strict=True with dynamic Literal types worked!")

    except Exception as e:
        print(f"\n❌ ERROR CAUGHT:")
        print(f"Exception Type: {type(e).__name__}")
        print(f"Exception Message: {e}")
        print(f"\nFull Traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
