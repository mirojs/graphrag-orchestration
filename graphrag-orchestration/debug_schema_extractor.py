
import asyncio
import os
from typing import List, Literal, get_args
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

    # Define entities and relations
    entities = ["ORGANIZATION", "PERSON", "LOCATION"]
    relations = ["CEO_OF", "PARTNERSHIP_WITH", "HEADQUARTERED_IN"]

    print(f"Testing SchemaLLMPathExtractor with entities={entities} and relations={relations}")

    # Try 1: Passing lists directly (as in the failing code)
    print("\n--- Attempt 1: Passing lists directly ---")
    try:
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=entities,
            possible_relations=relations,
            strict=False, # Try with strict=False
            num_workers=1
        )
        results = await extractor.acall(nodes)
        print(f"Results count: {len(results)}")
        for node in results:
            print(f"Metadata: {node.metadata}")
    except Exception as e:
        print(f"Attempt 1 failed: {e}")

    # Try 2: Using Literals (The 'Correct' Pydantic way)
    print("\n--- Attempt 2: Using Literals ---")
    try:
        # Dynamic creation of Literal is tricky in runtime, but let's try passing them if the class supports it
        # Actually SchemaLLMPathExtractor constructor type hint says: 
        # possible_entities: Optional[Union[List[str], Type[Literal]]]
        
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=entities, # It handles list conversion internally usually
            possible_relations=relations,
            strict=True, # Enforce strictness to see if it breaks
            num_workers=1
        )
        results = await extractor.acall(nodes)
        print(f"Results count: {len(results)}")
        for node in results:
            print(f"Metadata: {node.metadata}")
    except Exception as e:
        print(f"Attempt 2 failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
