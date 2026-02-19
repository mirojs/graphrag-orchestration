#!/usr/bin/env python3
"""Detect and materialize sub-sections for flat Section nodes via LLM.

Azure Document Intelligence sometimes misses sub-headings (e.g. bold text
rather than structural headings).  This script:

1. Finds flat Section nodes (depth 0, no children) with enough chunk text.
2. Sends the chunk text to an LLM to detect logical sub-headings.
3. Creates sub-Section nodes with summaries and structural embeddings.
4. Links existing TextChunks to the new sub-sections.
5. No runtime code changes — T2 automatically discovers new Section nodes.

Usage:
    python scripts/materialize_subsections.py --group test-5pdfs-v2-fix2 --dry-run
    python scripts/materialize_subsections.py --group test-5pdfs-v2-fix2 \\
        --openai-endpoint https://graphrag-openai-8476.openai.azure.com/
    python scripts/materialize_subsections.py --group test-5pdfs-v2-fix2 \\
        --doc-filter purchase_contract --clean
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AZURE_OPENAI_API_VERSION = "2024-10-21"


def get_neo4j_driver():
    """Create Neo4j driver from environment variables."""
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USERNAME", "")
    pw = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not pw:
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD must be set")
        sys.exit(1)
    return GraphDatabase.driver(uri, auth=(user, pw))


def get_azure_openai_token() -> Optional[str]:
    """Get Azure AD token for OpenAI via az CLI."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://cognitiveservices.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get Azure AD token: {e}")
        return None


def stable_section_id(group_id: str, doc_id: str, path_key: str) -> str:
    """Generate a stable hash-based section ID (matches pipeline convention)."""
    h = hashlib.sha256()
    h.update(group_id.encode("utf-8", errors="ignore"))
    h.update(b"\n")
    h.update(doc_id.encode("utf-8", errors="ignore"))
    h.update(b"\n")
    h.update(path_key.encode("utf-8", errors="ignore"))
    return f"section_{h.hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Step 1: Find flat sections with no sub-sections
# ---------------------------------------------------------------------------
def find_candidate_sections(
    driver, group_id: str, min_chunk_tokens: int = 200,
    doc_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find depth-0 sections with no children and enough chunk text."""
    doc_clause = ""
    params: Dict[str, Any] = {
        "group_id": group_id,
        "min_tokens": min_chunk_tokens,
    }
    if doc_filter:
        doc_clause = """
        AND EXISTS {
            MATCH (s)<-[:HAS_SECTION]-(d:Document {group_id: $group_id})
            WHERE toLower(d.title) CONTAINS toLower($doc_filter)
        }"""
        params["doc_filter"] = doc_filter

    query = f"""
    MATCH (s:Section {{group_id: $group_id}})
    WHERE s.depth = 0
      AND NOT EXISTS {{ MATCH (:Section)-[:SUBSECTION_OF]->(s) }}
      {doc_clause}
    WITH s
    MATCH (chunk)-[:IN_SECTION]->(s)
    WHERE chunk.group_id = $group_id
      AND (chunk:TextChunk OR chunk:Chunk OR chunk:`__Node__`)
    WITH s, collect({{
        id: chunk.id,
        text: chunk.text,
        tokens: coalesce(chunk.tokens, 0)
    }}) AS chunks
    WHERE reduce(t = 0, c IN chunks | t + c.tokens) >= $min_tokens
    RETURN s.id AS section_id, s.title AS title,
           s.doc_id AS doc_id, s.path_key AS path_key,
           s.depth AS depth, chunks
    ORDER BY s.title
    """
    with driver.session() as session:
        result = session.run(query, **params)
        return [dict(r) for r in result]


# ---------------------------------------------------------------------------
# Step 2: LLM sub-heading detection
# ---------------------------------------------------------------------------
def detect_subsections_llm(
    chunk_text: str,
    section_title: str,
    endpoint: str,
    deployment: str = "gpt-4.1",
) -> List[Dict[str, str]]:
    """Use LLM to detect logical sub-headings in flat section text."""
    import openai

    token = get_azure_openai_token()
    if not token:
        raise RuntimeError("Cannot get Azure AD token")

    client = openai.AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token=token,
        api_version=AZURE_OPENAI_API_VERSION,
    )

    prompt = (
        "You are analyzing a section of a legal/business document that may contain "
        "internal sub-headings that were not detected as structural sections.\n\n"
        f"Section title: {section_title}\n"
        f"Full text:\n---\n{chunk_text[:6000]}\n---\n\n"
        "Identify all distinct sub-sections or sub-topics within this text. "
        "For each, provide:\n"
        "1. title: The sub-heading text exactly as it appears in the document "
        "(e.g. \"Warranty\", \"Payment Terms\", \"Right to Cancel\")\n"
        "2. summary: A 1-2 sentence summary of what that sub-section covers, "
        "including specific key details such as parties, dollar amounts, "
        "time periods (days, weeks, months), percentages, and obligations.\n\n"
        "Return ONLY valid JSON — an array of objects:\n"
        '[{"title": "...", "summary": "..."}, ...]\n\n'
        "If the text has no identifiable sub-sections, return: []"
    )

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=2000,
    )
    text = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


# ---------------------------------------------------------------------------
# Step 3: Create sub-Section nodes + edges
# ---------------------------------------------------------------------------
def create_subsection_nodes(
    driver,
    group_id: str,
    parent_section_id: str,
    parent_path_key: str,
    parent_depth: int,
    doc_id: str,
    subsections: List[Dict[str, str]],
    dry_run: bool = False,
) -> int:
    """Create sub-Section nodes, SUBSECTION_OF edges, and IN_SECTION edges."""
    created = 0

    for sub in subsections:
        sub_title = sub["title"]
        sub_summary = sub.get("summary", "")
        sub_path_key = f"{parent_path_key} > {sub_title}"
        sub_id = stable_section_id(group_id, doc_id, sub_path_key)
        sub_depth = parent_depth + 1

        if dry_run:
            print(f"    [DRY RUN] {sub_path_key}")
            print(f"              ID: {sub_id}")
            print(f"              Summary: {sub_summary[:120]}...")
            print()
            created += 1
            continue

        # Create sub-Section node
        with driver.session() as session:
            session.run(
                """
                MERGE (sec:Section {id: $id})
                SET sec.group_id = $group_id,
                    sec.doc_id = $doc_id,
                    sec.path_key = $path_key,
                    sec.title = $title,
                    sec.depth = $depth,
                    sec.summary = $summary,
                    sec.source = 'llm_detected',
                    sec.updated_at = datetime()
                """,
                id=sub_id, group_id=group_id, doc_id=doc_id,
                path_key=sub_path_key, title=sub_title,
                depth=sub_depth, summary=sub_summary,
            )

        # Create SUBSECTION_OF edge to parent
        with driver.session() as session:
            session.run(
                """
                MATCH (sub:Section {id: $sub_id, group_id: $group_id})
                MATCH (parent:Section {id: $parent_id, group_id: $group_id})
                MERGE (sub)-[:SUBSECTION_OF]->(parent)
                """,
                sub_id=sub_id, parent_id=parent_section_id, group_id=group_id,
            )

        # Link ALL parent's TextChunks to this sub-section
        with driver.session() as session:
            session.run(
                """
                MATCH (chunk)-[:IN_SECTION]->(parent:Section {id: $parent_id, group_id: $group_id})
                WHERE chunk.group_id = $group_id
                MATCH (sub:Section {id: $sub_id, group_id: $group_id})
                MERGE (chunk)-[:IN_SECTION]->(sub)
                """,
                parent_id=parent_section_id, sub_id=sub_id, group_id=group_id,
            )

        created += 1

    return created


# ---------------------------------------------------------------------------
# Step 4: Generate structural embeddings for new sub-sections
# ---------------------------------------------------------------------------
def generate_structural_embeddings(
    driver, group_id: str,
) -> int:
    """Embed sub-sections that lack structural_embedding."""
    import voyageai

    api_key = os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        print("WARNING: VOYAGE_API_KEY not set, skipping embeddings")
        return 0

    # Fetch sub-sections needing embeddings
    query = """
    MATCH (s:Section {group_id: $group_id})
    WHERE s.structural_embedding IS NULL
      AND s.summary IS NOT NULL AND s.summary <> ''
    RETURN s.id AS id, s.title AS title,
           s.path_key AS path_key, s.summary AS summary
    """
    with driver.session() as session:
        result = session.run(query, group_id=group_id)
        sections = [dict(r) for r in result]

    if not sections:
        return 0

    # Build embedding texts (matches pipeline convention)
    texts = []
    for sec in sections:
        if sec["path_key"] and sec["title"] and sec["path_key"].endswith(sec["title"]):
            header = sec["path_key"]
        else:
            header = f"{sec['title']} | {sec['path_key']}" if sec["path_key"] else sec["title"]
        combined = f"{header} — {sec['summary']}" if sec["summary"] else header
        texts.append(combined[:600])

    # Embed via Voyage contextualized_embed (matches pipeline convention)
    vc = voyageai.Client(api_key=api_key)
    # Use contextualized_embed with input_type="document" — same as pipeline
    result = vc.contextualized_embed(
        inputs=[texts],  # Single "document" with all sub-section texts as chunks
        model="voyage-context-3",
        input_type="document",
        output_dimension=2048,
    )
    embeddings = result.results[0].embeddings

    # Store embeddings
    for sec, embedding in zip(sections, embeddings):
        with driver.session() as session:
            session.run(
                """
                MATCH (s:Section {id: $id, group_id: $group_id})
                SET s.structural_embedding = $embedding,
                    s.updated_at = datetime()
                """,
                id=sec["id"], group_id=group_id, embedding=embedding,
            )

    return len(sections)


# ---------------------------------------------------------------------------
# Step 5: Clear parent embedding so it regenerates
# ---------------------------------------------------------------------------
def clear_parent_embeddings(
    driver, group_id: str, parent_section_ids: List[str],
) -> int:
    """Clear structural_embedding and summary on parent sections."""
    if not parent_section_ids:
        return 0
    with driver.session() as session:
        result = session.run(
            """
            UNWIND $ids AS sid
            MATCH (s:Section {id: sid, group_id: $group_id})
            SET s.structural_embedding = null,
                s.summary = null,
                s.updated_at = datetime()
            RETURN count(s) AS cnt
            """,
            ids=parent_section_ids, group_id=group_id,
        )
        return result.single()["cnt"]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def delete_llm_detected_subsections(driver, group_id: str) -> int:
    """Delete sub-sections previously created by this script."""
    with driver.session() as session:
        cnt = session.run(
            "MATCH (s:Section {group_id: $group_id, source: 'llm_detected'}) "
            "RETURN count(s) AS cnt",
            group_id=group_id,
        ).single()["cnt"]
        if cnt > 0:
            session.run(
                "MATCH (s:Section {group_id: $group_id, source: 'llm_detected'}) "
                "DETACH DELETE s",
                group_id=group_id,
            )
    return cnt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Detect and materialize sub-sections for flat Section nodes via LLM"
    )
    parser.add_argument("--group", required=True, help="Group ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to Neo4j")
    parser.add_argument("--doc-filter", default=None,
                        help="Only process sections belonging to documents matching this (case-insensitive)")
    parser.add_argument("--min-chunk-tokens", type=int, default=200,
                        help="Min total chunk tokens for a section to be a candidate (default: 200)")
    parser.add_argument("--clean", action="store_true",
                        help="Delete existing LLM-detected sub-sections before creating new ones")
    parser.add_argument("--openai-endpoint", default=None,
                        help="Azure OpenAI endpoint URL")
    parser.add_argument("--openai-deployment", default="gpt-4.1",
                        help="Azure OpenAI deployment name (default: gpt-4.1)")
    args = parser.parse_args()

    endpoint = args.openai_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    if not endpoint and not args.dry_run:
        print("ERROR: --openai-endpoint or AZURE_OPENAI_ENDPOINT required (unless --dry-run)")
        sys.exit(1)

    print("=" * 70)
    print("SUB-SECTION MATERIALIZATION")
    print("=" * 70)
    print(f"  Group ID:        {args.group}")
    print(f"  Doc filter:      {args.doc_filter or '(all)'}")
    print(f"  Min chunk tokens: {args.min_chunk_tokens}")
    print(f"  Dry run:         {args.dry_run}")
    print(f"  Clean:           {args.clean}")
    print()

    driver = get_neo4j_driver()

    # Clean existing LLM-detected sub-sections if requested
    if args.clean:
        deleted = delete_llm_detected_subsections(driver, args.group)
        print(f"Cleaned {deleted} existing LLM-detected sub-sections")
        print()

    # Step 1: Find candidate flat sections
    print("Step 1: Finding candidate flat sections...")
    candidates = find_candidate_sections(
        driver, args.group, args.min_chunk_tokens, args.doc_filter,
    )
    print(f"  Found {len(candidates)} candidate sections")
    for c in candidates:
        total_tokens = sum(ch["tokens"] for ch in c["chunks"])
        print(f"    {c['title']} ({len(c['chunks'])} chunks, {total_tokens} tokens)")
    print()

    if not candidates:
        print("No candidate sections found.")
        driver.close()
        return

    # Step 2: Detect sub-sections via LLM
    print("Step 2: Detecting sub-sections via LLM...")
    total_created = 0
    parent_ids_modified = []

    for candidate in candidates:
        section_title = candidate["title"]
        print(f"\n  Processing: {section_title}")

        # Concatenate chunk texts
        chunk_text = "\n\n".join(ch["text"] for ch in candidate["chunks"] if ch["text"])

        if args.dry_run and not endpoint:
            print(f"    [DRY RUN] Would send {len(chunk_text)} chars to LLM")
            continue

        try:
            subsections = detect_subsections_llm(
                chunk_text, section_title, endpoint, args.openai_deployment,
            )
        except Exception as e:
            print(f"    ERROR: LLM detection failed: {e}")
            continue

        if len(subsections) < 2:
            print(f"    Skipped: only {len(subsections)} sub-section(s) detected (need >= 2)")
            continue

        print(f"    Detected {len(subsections)} sub-sections:")
        for sub in subsections:
            print(f"      - {sub['title']}: {sub.get('summary', '')[:80]}...")

        # Step 3: Create sub-Section nodes + edges
        created = create_subsection_nodes(
            driver, args.group,
            parent_section_id=candidate["section_id"],
            parent_path_key=candidate["path_key"],
            parent_depth=candidate["depth"],
            doc_id=candidate["doc_id"],
            subsections=subsections,
            dry_run=args.dry_run,
        )
        total_created += created
        if not args.dry_run:
            parent_ids_modified.append(candidate["section_id"])

    print(f"\n  Total sub-sections created: {total_created}")
    print()

    if args.dry_run:
        print("Dry run complete. No changes written to Neo4j.")
        driver.close()
        return

    # Step 4: Generate structural embeddings
    print("Step 4: Generating structural embeddings for new sub-sections...")
    t0 = time.time()
    embedded = generate_structural_embeddings(driver, args.group)
    elapsed = time.time() - t0
    print(f"  Embedded {embedded} sections in {elapsed:.1f}s")
    print()

    # Step 5: Clear parent embeddings
    if parent_ids_modified:
        print("Step 5: Clearing parent section embeddings (will regenerate)...")
        cleared = clear_parent_embeddings(driver, args.group, parent_ids_modified)
        print(f"  Cleared embeddings from {cleared} parent sections")
        print()

    # Verify
    with driver.session() as session:
        result = session.run(
            """
            MATCH (sub:Section {group_id: $group_id, source: 'llm_detected'})
            OPTIONAL MATCH (sub)-[:SUBSECTION_OF]->(parent:Section)
            RETURN parent.title AS parent, sub.title AS sub_title,
                   sub.summary AS summary,
                   sub.structural_embedding IS NOT NULL AS has_embedding
            ORDER BY parent.title, sub.title
            """,
            group_id=args.group,
        )
        rows = [dict(r) for r in result]

    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Sub-sections created: {total_created}")
    print(f"  Embeddings generated: {embedded}")
    print()
    if rows:
        print("  Sub-section details:")
        for row in rows:
            emb = "✓" if row["has_embedding"] else "✗"
            print(f"    [{emb}] {row['parent']} > {row['sub_title']}")
            if row["summary"]:
                print(f"        {row['summary'][:100]}...")
    print("=" * 70)

    driver.close()


if __name__ == "__main__":
    main()
