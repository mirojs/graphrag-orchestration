"""Generate LLM summaries for materialized community nodes."""
import os, sys, json, time, subprocess
sys.path.insert(0, '/afh/projects/graphrag-orchestration')

from neo4j import GraphDatabase
import requests

NEO4J_URI = 'neo4j+s://a86dcf63.databases.neo4j.io'
NEO4J_USER = 'neo4j'
NEO4J_PASS = 'uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI'
GID = 'test-5pdfs-v2-fix2'
AOAI_ENDPOINT = 'https://graphrag-openai-8476.openai.azure.com'
AOAI_DEPLOYMENT = 'gpt-4.1'
AOAI_API_VERSION = '2024-10-21'

# Get AOAI token
token = subprocess.check_output(
    ['az', 'account', 'get-access-token', '--resource', 'https://cognitiveservices.azure.com', '--query', 'accessToken', '-o', 'tsv'],
    text=True
).strip()

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

# Get communities with their entities
with driver.session(database='neo4j') as session:
    result = session.run("""
        MATCH (e:Entity {group_id: $gid})
        WHERE e.community_id IS NOT NULL
        WITH e.community_id AS cid,
             collect({
                 name: e.name,
                 description: coalesce(e.description, ''),
                 degree: coalesce(e.degree, 0),
                 pagerank: coalesce(e.pagerank, 0.0),
                 id: id(e)
             }) AS members
        WHERE size(members) >= 2
        RETURN cid, members
        ORDER BY size(members) DESC
    """, gid=GID)
    community_groups = [(r["cid"], r["members"]) for r in result]

print(f"Found {len(community_groups)} communities to summarize")

def get_relationships(cid):
    """Get intra-community relationships."""
    with driver.session(database='neo4j') as session:
        result = session.run("""
            MATCH (e1:Entity {group_id: $gid})-[r]->(e2:Entity {group_id: $gid})
            WHERE e1.community_id = $cid
              AND e2.community_id = $cid
              AND NOT type(r) IN ['MENTIONS', 'SEMANTICALLY_SIMILAR', 'BELONGS_TO', 'APPEARS_IN_SECTION', 'APPEARS_IN_DOCUMENT']
            RETURN e1.name AS source, type(r) AS rel_type, e2.name AS target,
                   coalesce(r.description, '') AS description
            LIMIT 50
        """, gid=GID, cid=cid)
        return [dict(rec) for rec in result]

def call_llm(prompt):
    """Call Azure OpenAI."""
    url = f"{AOAI_ENDPOINT}/openai/deployments/{AOAI_DEPLOYMENT}/chat/completions?api-version={AOAI_API_VERSION}"
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }, json={
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.3
    })
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

def parse_summary(text):
    """Parse TITLE: / SUMMARY: from LLM response."""
    title = ""
    summary = ""
    for line in text.split("\n"):
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("SUMMARY:"):
            summary = line[8:].strip()
    if not summary:
        summary = text[:500]
    if not title:
        title = summary[:50] + ("..." if len(summary) > 50 else "")
    return title, summary

# Process each community
for i, (cid, members) in enumerate(community_groups):
    relationships = get_relationships(cid)
    
    # Build entity list
    entity_lines = []
    for m in sorted(members, key=lambda x: x["pagerank"], reverse=True)[:30]:
        desc = f" — {m['description']}" if m["description"] else ""
        entity_lines.append(f"- {m['name']}{desc}")
    
    # Build relationship list
    rel_lines = []
    for r in relationships[:30]:
        desc = f" ({r['description']})" if r.get("description") else ""
        rel_lines.append(f"- {r['source']} → {r['rel_type']} → {r['target']}{desc}")
    
    prompt = f"""You are analyzing a group of related entities from a knowledge graph of legal/business documents.

ENTITIES IN THIS CLUSTER ({len(members)} entities):
{chr(10).join(entity_lines)}

RELATIONSHIPS BETWEEN THEM ({len(relationships)} relationships):
{chr(10).join(rel_lines) if rel_lines else '(No explicit relationships extracted)'}

Based on these entities and their relationships, provide:
1. TITLE: A short descriptive title for this cluster (5-10 words)
2. SUMMARY: A 2-3 sentence summary describing what this group of entities represents, what topics or themes it covers, and what types of questions it could help answer. Be specific about the domain terms and party names.

Format your response exactly as:
TITLE: <title>
SUMMARY: <summary>"""

    try:
        response_text = call_llm(prompt)
        title, summary = parse_summary(response_text)
        
        community_id = f"louvain_{GID}_{cid}"
        avg_pr = sum(m["pagerank"] for m in members) / len(members)
        
        # Update community node
        with driver.session(database='neo4j') as session:
            session.run("""
                MATCH (c:Community {id: $cid, group_id: $gid})
                SET c.title = $title, c.summary = $summary, c.rank = $rank
            """, cid=community_id, gid=GID, title=title, summary=summary, rank=avg_pr)
        
        print(f"  [{i+1}/{len(community_groups)}] ({len(members)} entities) {title}")
    except Exception as e:
        print(f"  [{i+1}/{len(community_groups)}] FAILED: {e}")
    
    time.sleep(0.2)  # Rate limiting

# Verify
with driver.session(database='neo4j') as session:
    r = session.run("""
        MATCH (c:Community {group_id: $gid})
        WHERE c.summary IS NOT NULL AND c.summary <> ''
        RETURN c.title AS title, c.size AS size, substring(c.summary, 0, 80) AS summary_preview
        ORDER BY c.size DESC
        LIMIT 10
    """, gid=GID)
    print("\nTop 10 communities with LLM summaries:")
    for rec in r:
        print(f"  [{rec['size']}] {rec['title']}")
        print(f"      {rec['summary_preview']}...")

driver.close()
