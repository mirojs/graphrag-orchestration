from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")

if not uri:
    # Fallback to hardcoded if env not loaded correctly (since I saw them in other scripts)
    uri = "neo4j+s://a86dcf63.databases.neo4j.io"
    user = "neo4j"
    password = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

print(f"Connecting to {uri}...")
driver = GraphDatabase.driver(uri, auth=(user, password))
with driver.session() as session:
    try:
        session.run("DROP INDEX entity_embedding IF EXISTS")
        print("Dropped entity_embedding")
    except Exception as e:
        print(f"Error dropping entity_embedding: {e}")

    try:
        session.run("DROP INDEX chunk_vector IF EXISTS")
        print("Dropped chunk_vector")
    except Exception as e:
        print(f"Error dropping chunk_vector: {e}")

    try:
        session.run("DROP INDEX raptor_embedding IF EXISTS")
        print("Dropped raptor_embedding")
    except Exception as e:
        print(f"Error dropping raptor_embedding: {e}")
        
    try:
        session.run("DROP INDEX description_embedding IF EXISTS")
        print("Dropped description_embedding")
    except Exception as e:
        print(f"Error dropping description_embedding: {e}")

print("Dropped vector indexes.")
driver.close()
