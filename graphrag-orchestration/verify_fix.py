
import asyncio
import os
from typing import List
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.schema import TextNode
from llama_index.llms.azure_openai import AzureOpenAI
from app.core.config import settings

# Mock config if needed, or rely on env vars
# Assuming env vars are set in the environment

async def main():
    print("Initializing LLM...")
    llm = AzureOpenAI(
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )

    text = """
    Microsoft Corporation is a technology company headquartered in Redmond, Washington.
    Satya Nadella is the CEO of Microsoft.
    Microsoft announced a new partnership with OpenAI.
    """
    
    nodes = [TextNode(text=text)]

    # Define entities and relations as per indexing_pipeline.py
    entity_types = [
        "PERSON", "ORGANIZATION", "LOCATION", "EVENT", 
        "PRODUCT", "CONCEPT", "DATE", "MONEY"
    ]
    
    possible_relations = [
        "RELATED_TO", "HAS_PART", "IS_A", "WORKS_FOR", "LOCATED_AT", 
        "INVOLVES", "HAS_AMOUNT", "HAS_DATE", "MENTIONS", "DEFINES",
        "OWNS", "MANAGES", "PARTICIPATES_IN", "AFFECTS"
    ]

    print(f"Testing SchemaLLMPathExtractor with strict=False (The Fix)")
    print(f"Entities: {entity_types}")
    print(f"Relations: {possible_relations}")

    try:
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=entity_types,
            possible_relations=possible_relations,
            strict=False, # The Fix
            num_workers=1
        )
        results = await extractor.acall(nodes)
        print(f"\n✅ Success! Extracted {len(results)} nodes.")
        
        print("\nExtracted Metadata:")
        for node in results:
            print(f"{node.metadata}")
            
    except Exception as e:
        print(f"\n❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
