import asyncio
import uuid
from typing import List, Dict, Any
from llama_index.core.schema import TextNode
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.llms.azure_openai import AzureOpenAI
from pydantic import BaseModel, Field

# Mock Entity and Relationship classes
class Entity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    embedding: List[float] = Field(default_factory=list)

class Relationship(BaseModel):
    source_id: str
    target_id: str
    description: str
    weight: float = 1.0

# Setup LLM (using the same config as verify_fix_thorough.py)
llm = AzureOpenAI(
    engine="gpt-4o",
    model="gpt-4o",
    api_key="76830926-fd40-4223-9036-e6233f233a8f",
    azure_endpoint="https://ai-proxy.lab.epam.com",
    api_version="2024-02-01",
    timeout=60.0
)

async def run_test():
    print("Starting pipeline reproduction...")
    
    # 1. Setup Extractor
    entities = ["PERSON", "ORG", "LOC", "EVENT", "PRODUCT"]
    relations = ["WORKS_FOR", "LOCATED_AT", "PART_OF", "HAS_EVENT", "ANNOUNCED"]
    
    extractor = SchemaLLMPathExtractor(
        llm=llm,
        possible_entities=entities,
        possible_relations=relations,
        strict=False,
        num_workers=1
    )
    
    # 2. Create Input Node
    text = "Apple Inc. announced the new iPhone 15 at their headquarters in Cupertino, California. Tim Cook presented the device."
    nodes = [TextNode(text=text, id_="node_1")]
    
    # 3. Extract
    print("Extracting...")
    extracted_nodes = await extractor.acall(nodes)
    print(f"Extracted {len(extracted_nodes)} nodes")
    
    # 4. Simulate Indexing Pipeline Logic
    temp_graph_store = SimplePropertyGraphStore()
    
    all_entity_nodes = []
    all_relations = []
    
    for node in extracted_nodes:
        print(f"Node metadata keys: {node.metadata.keys()}")
        if "kg_nodes" in node.metadata:
            all_entity_nodes.extend(node.metadata["kg_nodes"])
        if "kg_relations" in node.metadata:
            all_relations.extend(node.metadata["kg_relations"])
            
    print(f"Found {len(all_entity_nodes)} entity nodes in metadata")
    print(f"Found {len(all_relations)} relations in metadata")
    
    # 5. Upsert to Graph Store
    temp_graph_store.upsert_nodes(all_entity_nodes)
    temp_graph_store.upsert_relations(all_relations)
    
    graph = temp_graph_store.graph
    graph_nodes = graph.nodes
    graph_relations = graph.relations
    
    print(f"Graph Store: {len(graph_nodes)} nodes, {len(graph_relations)} relations")
    
    # 6. Manual Extraction Logic (from indexing_pipeline.py)
    all_entities: Dict[str, Entity] = {}
    all_relationships: List[Relationship] = []
    name_to_id_map = {}
    
    # Process Nodes
    for node_id, node in graph_nodes.items():
        # Logic from pipeline
        entity_name = None
        if hasattr(node, "name") and node.name:
            entity_name = node.name
        elif hasattr(node, "properties") and "name" in node.properties:
            entity_name = node.properties["name"]
        else:
            entity_name = str(node_id)
            
        if not entity_name or entity_name == "entity":
             if node_id != "entity":
                 entity_name = str(node_id)
             else:
                 continue

        entity_key = entity_name.lower()
        
        if entity_key not in all_entities:
            new_id = f"entity_{uuid.uuid4().hex[:8]}"
            all_entities[entity_key] = Entity(
                id=new_id,
                name=entity_name,
                type=node.label if hasattr(node, 'label') else "CONCEPT",
                description=str(node.properties) if hasattr(node, 'properties') else "",
            )
            name_to_id_map[entity_key] = new_id
        else:
            name_to_id_map[entity_key] = all_entities[entity_key].id
            
    print(f"Processed {len(all_entities)} entities")
    print(f"Name map keys: {list(name_to_id_map.keys())}")
    
    # Process Relations
    for relation_id, relation in graph_relations.items():
        source_name = relation.source_id
        target_name = relation.target_id
        
        # Fallback logic
        if source_name not in name_to_id_map:
             source_node = graph_nodes.get(source_name)
             if source_node:
                 if hasattr(source_node, "name") and source_node.name:
                     source_name = source_node.name
                 elif hasattr(source_node, "properties") and "name" in source_node.properties:
                     source_name = source_node.properties["name"]

        if target_name not in name_to_id_map:
             target_node = graph_nodes.get(target_name)
             if target_node:
                 if hasattr(target_node, "name") and target_node.name:
                     target_name = target_node.name
                 elif hasattr(target_node, "properties") and "name" in target_node.properties:
                     target_name = target_node.properties["name"]
        
        source_key = str(source_name).lower()
        target_key = str(target_name).lower()
        
        print(f"Relation: {source_name} -> {target_name}")
        print(f"Keys: {source_key} -> {target_key}")
        
        source_entity_id = name_to_id_map.get(source_key)
        target_entity_id = name_to_id_map.get(target_key)
        
        if source_entity_id and target_entity_id:
            rel = Relationship(
                source_id=source_entity_id,
                target_id=target_entity_id,
                description=relation.label,
            )
            all_relationships.append(rel)
        else:
            print(f"❌ Failed to map relation: {source_key} ({source_entity_id}) -> {target_key} ({target_entity_id})")

    print(f"Final Relationships: {len(all_relationships)}")

if __name__ == "__main__":
    asyncio.run(run_test())
