
import asyncio
import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.llm_service import LLMService
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.schema import TextNode

async def main():
    print("Initializing LLM Service...")
    llm_service = LLMService()
    llm = llm_service.llm
    
    if not llm:
        print("ERROR: LLM not initialized. Check environment variables.")
        return

    print(f"LLM Initialized: {llm.model}")

    # Define possible relations (same as in indexing_pipeline.py)
    possible_relations = [
        "RELATED_TO", "HAS_PART", "IS_A", "WORKS_FOR", "LOCATED_AT", 
        "INVOLVES", "HAS_AMOUNT", "HAS_DATE", "MENTIONS", "DEFINES",
        "OWNS", "MANAGES", "PARTICIPATES_IN", "AFFECTS"
    ]
    
    # Create extractor
    print("Creating SchemaLLMPathExtractor...")
    
    from typing import Literal
    
    # Dynamic Literal creation
    entities_list = ["Person", "Organization", "Location", "Event", "Concept"]
    relations_list = [
        "RELATED_TO", "HAS_PART", "IS_A", "WORKS_FOR", "LOCATED_AT", 
        "INVOLVES", "HAS_AMOUNT", "HAS_DATE", "MENTIONS", "DEFINES",
        "OWNS", "MANAGES", "PARTICIPATES_IN", "AFFECTS"
    ]
    
    EntityLiteral = Literal[tuple(entities_list)]
    RelationLiteral = Literal[tuple(relations_list)]

    # Note: Removed max_paths_per_chunk as per the fix
    extractor = SchemaLLMPathExtractor(
        llm=llm,
        possible_entities=EntityLiteral, 
        possible_relations=RelationLiteral,
        num_workers=1, # Use 1 for debugging
    )
    
    # Create a sample node
    text = """
    Microsoft Corporation is a technology company located in Redmond, Washington.
    Satya Nadella works for Microsoft as the CEO.
    The company announced a new AI product on October 2023.
    """
    
    node = TextNode(text=text, id_="test-node-1")
    nodes = [node]
    
    print(f"Extracting from text: {text.strip()}")
    
    try:
        extracted_nodes = await extractor.acall(nodes)
        print(f"Extracted {len(extracted_nodes)} nodes.")
        
        for i, node in enumerate(extracted_nodes):
            print(f"Node {i} metadata keys: {node.metadata.keys()}")
            if "kg_relations" in node.metadata:
                print(f"Node {i} kg_relations: {node.metadata['kg_relations']}")
            if "relations" in node.metadata:
                print(f"Node {i} relations: {node.metadata['relations']}")
            if "nodes" in node.metadata:
                print(f"Node {i} nodes: {node.metadata['nodes']}")
            if "kg_nodes" in node.metadata:
                print(f"Node {i} kg_nodes: {node.metadata['kg_nodes']}")
                
    except Exception as e:
        print(f"Extraction failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
