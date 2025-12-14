
import asyncio
import os
from typing import List, Set
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

    # Complex text with potential for ambiguity
    text = """
    Apple Inc. reported record quarterly revenue. 
    Tim Cook, the CEO, announced the new iPhone 15 at the event in Cupertino.
    The device costs $999.
    The board meeting happened on September 12, 2023.
    Google is a competitor located in Mountain View.
    """
    
    nodes = [TextNode(text=text)]

    # Define a STRICT schema
    # Note: We use "COMPANY" instead of "ORGANIZATION" to see if LLM follows instructions
    # or defaults to its training (which often prefers ORGANIZATION)
    entity_types = [
        "PERSON", "COMPANY", "CITY", "EVENT", "PRODUCT", "DATE", "MONEY"
    ]
    
    possible_relations = [
        "LEADER_OF", "LOCATED_IN", "ANNOUNCED", "COSTS", "COMPETES_WITH", "HAPPENED_ON"
    ]

    print(f"\n--- TEST CONFIGURATION ---")
    print(f"Strict Mode: False")
    print(f"Allowed Entities: {entity_types}")
    print(f"Allowed Relations: {possible_relations}")
    print(f"Input Text: {text.strip()}")

    try:
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            possible_entities=entity_types,
            possible_relations=possible_relations,
            strict=False, # The setting under test
            num_workers=1
        )
        results = await extractor.acall(nodes)
        
        print(f"\n--- EXTRACTION RESULTS ---")
        print(f"Total Extracted Items: {len(results)}")
        
        entities = []
        relations = []
        
        # Separate entities and relations from the results
        # LlamaIndex returns a list of BaseNode, where some are EntityNode and some are Relation (wrapped)
        # Actually SchemaLLMPathExtractor returns a list of BaseNode (TextNode) with metadata populated
        # Let's inspect the metadata of the returned nodes
        
        extracted_entities_count = 0
        extracted_relations_count = 0
        
        non_compliant_entities = []
        non_compliant_relations = []

        for node in results:
            # The extractor returns the original nodes with metadata added
            node_entities = node.metadata.get("kg_nodes", []) + node.metadata.get("nodes", [])
            node_relations = node.metadata.get("kg_relations", []) + node.metadata.get("relations", [])
            
            for entity in node_entities:
                # entity is likely a dict or EntityNode object
                # In recent LlamaIndex versions, it might be an object
                label = getattr(entity, "label", None) or entity.get("label")
                name = getattr(entity, "name", None) or entity.get("name")
                
                extracted_entities_count += 1
                if label not in entity_types:
                    non_compliant_entities.append(f"{name} ({label})")
                else:
                    print(f"✅ Entity: {name} [{label}]")

            for rel in node_relations:
                label = getattr(rel, "label", None) or rel.get("label")
                source = getattr(rel, "source_id", None) or rel.get("source_id")
                target = getattr(rel, "target_id", None) or rel.get("target_id")
                
                extracted_relations_count += 1
                if label not in possible_relations:
                    non_compliant_relations.append(f"{source} --[{label}]--> {target}")
                else:
                    print(f"✅ Relation: {source} --[{label}]--> {target}")

        print(f"\n--- COMPLIANCE REPORT ---")
        print(f"Entities: {extracted_entities_count - len(non_compliant_entities)}/{extracted_entities_count} compliant")
        if non_compliant_entities:
            print(f"⚠️  Non-Compliant Entities (Hallucinations):")
            for e in non_compliant_entities:
                print(f"   - {e}")
        else:
            print("🎉 All entities followed the schema!")

        print(f"Relations: {extracted_relations_count - len(non_compliant_relations)}/{extracted_relations_count} compliant")
        if non_compliant_relations:
            print(f"⚠️  Non-Compliant Relations (Hallucinations):")
            for r in non_compliant_relations:
                print(f"   - {r}")
        else:
            print("🎉 All relations followed the schema!")
            
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
