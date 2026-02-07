#!/usr/bin/env python3
"""
Comprehensive graph validation for LazyGraphRAG indexing pipeline.

Checks ALL node types, edge types, embeddings, GDS properties, and structural
integrity for both V1 (hybrid) and V2 (hybrid_v2) indexed groups.

Usage:
    python check_edges.py <group_id>                    # Check specific group
    python check_edges.py                               # Use last_test_group_id.txt or default
    python check_edges.py <group_id> --quick             # Node counts + edges only
    python check_edges.py <group_id> --json              # JSON output for automation
    python check_edges.py <group_id> --expected-docs 5   # Validate expected doc count
"""

from neo4j import GraphDatabase
import os
import sys
import json
import argparse
from collections import OrderedDict


def pct(part, total):
    return f"{100 * part // total}%" if total > 0 else "N/A"


def status_icon(ok):
    return "✅" if ok else "❌"


def section_header(title, width=70):
    print(f"\n{'=' * width}")
    print(title)
    print(f"{'=' * width}")


def count_query(session, cypher, **params):
    result = session.run(cypher, **params)
    return result.single()["count"]


def build_report(session, group_id, args):
    """Build comprehensive graph validation report."""
    report = OrderedDict()
    issues = []

    # ──────────────────────────────────────────────────────────────────
    # 1. NODE COUNTS
    # ──────────────────────────────────────────────────────────────────
    node_types = [
        ("Document",      "MATCH (n:Document {group_id: $gid}) RETURN count(n) as count"),
        ("TextChunk",     "MATCH (n:TextChunk {group_id: $gid}) RETURN count(n) as count"),
        ("Section",       "MATCH (n:Section {group_id: $gid}) RETURN count(n) as count"),
        ("Entity",        "MATCH (n:Entity {group_id: $gid}) RETURN count(n) as count"),
        ("Table",         "MATCH (n:Table {group_id: $gid}) RETURN count(n) as count"),
        ("KeyValue",      "MATCH (n:KeyValue {group_id: $gid}) RETURN count(n) as count"),
        ("KeyValuePair",  "MATCH (n:KeyValuePair {group_id: $gid}) RETURN count(n) as count"),
        ("Figure",        "MATCH (n:Figure {group_id: $gid}) RETURN count(n) as count"),
        ("Barcode",       "MATCH (n:Barcode {group_id: $gid}) RETURN count(n) as count"),
        ("Community",     "MATCH (n:Community {group_id: $gid}) RETURN count(n) as count"),
        ("GroupMeta",     "MATCH (n:GroupMeta {group_id: $gid}) RETURN count(n) as count"),
    ]
    nodes = OrderedDict()
    for label, cypher in node_types:
        nodes[label] = count_query(session, cypher, gid=group_id)
    report["nodes"] = nodes

    # Validate expected doc count if provided
    if args.expected_docs and nodes["Document"] != args.expected_docs:
        issues.append(f"Expected {args.expected_docs} Documents, found {nodes['Document']}")

    # ──────────────────────────────────────────────────────────────────
    # 2. STRUCTURAL EDGES (Document ↔ Section ↔ TextChunk hierarchy)
    # ──────────────────────────────────────────────────────────────────
    structural_edges = OrderedDict()

    # IN_DOCUMENT: TextChunk → Document
    structural_edges["IN_DOCUMENT (TextChunk→Doc)"] = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid})-[r:IN_DOCUMENT]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    # PART_OF: TextChunk → Document (legacy V1)
    structural_edges["PART_OF (TextChunk→Doc, legacy)"] = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid})-[r:PART_OF]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    # HAS_SECTION: Document → Section (top-level)
    structural_edges["HAS_SECTION (Doc→Section)"] = count_query(session, '''
        MATCH (d:Document {group_id: $gid})-[r:HAS_SECTION]->(s:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # SUBSECTION_OF: Section → Section (child → parent)
    structural_edges["SUBSECTION_OF (Section→Section)"] = count_query(session, '''
        MATCH (s1:Section {group_id: $gid})-[r:SUBSECTION_OF]->(s2:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_SECTION: TextChunk → Section
    structural_edges["IN_SECTION (TextChunk→Section)"] = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid})-[r:IN_SECTION]->(s:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_SECTION: Table → Section
    structural_edges["IN_SECTION (Table→Section)"] = count_query(session, '''
        MATCH (t:Table {group_id: $gid})-[r:IN_SECTION]->(s:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_SECTION: KeyValue → Section
    structural_edges["IN_SECTION (KeyValue→Section)"] = count_query(session, '''
        MATCH (kv:KeyValue {group_id: $gid})-[r:IN_SECTION]->(s:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_DOCUMENT: Table → Document
    structural_edges["IN_DOCUMENT (Table→Doc)"] = count_query(session, '''
        MATCH (t:Table {group_id: $gid})-[r:IN_DOCUMENT]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_DOCUMENT: KeyValue → Document
    structural_edges["IN_DOCUMENT (KeyValue→Doc)"] = count_query(session, '''
        MATCH (kv:KeyValue {group_id: $gid})-[r:IN_DOCUMENT]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_CHUNK: Table → TextChunk
    structural_edges["IN_CHUNK (Table→TextChunk)"] = count_query(session, '''
        MATCH (t:Table {group_id: $gid})-[r:IN_CHUNK]->(c:TextChunk)
        RETURN count(r) as count
    ''', gid=group_id)

    # IN_CHUNK: KeyValue → TextChunk
    structural_edges["IN_CHUNK (KeyValue→TextChunk)"] = count_query(session, '''
        MATCH (kv:KeyValue {group_id: $gid})-[r:IN_CHUNK]->(c:TextChunk)
        RETURN count(r) as count
    ''', gid=group_id)

    report["structural_edges"] = structural_edges

    # Check chunk→doc connectivity
    chunk_doc_total = structural_edges["IN_DOCUMENT (TextChunk→Doc)"] + structural_edges["PART_OF (TextChunk→Doc, legacy)"]
    if nodes["TextChunk"] > 0 and chunk_doc_total == 0:
        issues.append(f"No TextChunk→Document edges (IN_DOCUMENT or PART_OF): provenance broken")
    elif nodes["TextChunk"] > 0 and chunk_doc_total < nodes["TextChunk"]:
        issues.append(f"Only {chunk_doc_total}/{nodes['TextChunk']} TextChunks linked to Documents")

    # Check orphan sections
    orphan_sections = count_query(session, '''
        MATCH (s:Section {group_id: $gid})
        WHERE NOT (s)<-[:HAS_SECTION]-(:Document)
          AND NOT (s)-[:SUBSECTION_OF]->(:Section)
        RETURN count(s) as count
    ''', gid=group_id)
    report["orphan_sections"] = orphan_sections
    if orphan_sections > 0:
        issues.append(f"{orphan_sections} orphan Sections (no HAS_SECTION or SUBSECTION_OF parent)")

    # ──────────────────────────────────────────────────────────────────
    # 3. ENTITY / KNOWLEDGE EDGES
    # ──────────────────────────────────────────────────────────────────
    entity_edges = OrderedDict()

    entity_edges["MENTIONS (TextChunk→Entity)"] = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid})-[r:MENTIONS]->(e:Entity)
        RETURN count(r) as count
    ''', gid=group_id)

    entity_edges["RELATED_TO (Entity→Entity)"] = count_query(session, '''
        MATCH (e1:Entity {group_id: $gid})-[r:RELATED_TO]->(e2:Entity)
        RETURN count(r) as count
    ''', gid=group_id)

    report["entity_edges"] = entity_edges

    # ──────────────────────────────────────────────────────────────────
    # 4. FOUNDATION EDGES (Phase 1)
    # ──────────────────────────────────────────────────────────────────
    foundation_edges = OrderedDict()

    foundation_edges["APPEARS_IN_SECTION (Entity→Section)"] = count_query(session, '''
        MATCH (e:Entity)-[r:APPEARS_IN_SECTION]->(s:Section {group_id: $gid})
        RETURN count(r) as count
    ''', gid=group_id)

    foundation_edges["APPEARS_IN_DOCUMENT (Entity→Doc)"] = count_query(session, '''
        MATCH (e:Entity)-[r:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $gid})
        RETURN count(r) as count
    ''', gid=group_id)

    foundation_edges["HAS_HUB_ENTITY (Section→Entity)"] = count_query(session, '''
        MATCH (s:Section {group_id: $gid})-[r:HAS_HUB_ENTITY]->(e:Entity)
        RETURN count(r) as count
    ''', gid=group_id)

    report["foundation_edges"] = foundation_edges

    # ──────────────────────────────────────────────────────────────────
    # 5. CONNECTIVITY EDGES (Phase 2)
    # ──────────────────────────────────────────────────────────────────
    connectivity_edges = OrderedDict()

    connectivity_edges["SHARES_ENTITY (Section↔Section)"] = count_query(session, '''
        MATCH (s1:Section {group_id: $gid})-[r:SHARES_ENTITY]->(s2:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    report["connectivity_edges"] = connectivity_edges

    # ──────────────────────────────────────────────────────────────────
    # 6. SEMANTIC EDGES (Phase 3 — V1 legacy + V2)
    # ──────────────────────────────────────────────────────────────────
    semantic_edges = OrderedDict()

    # V1: SIMILAR_TO (Entity ↔ Entity, cosine > 0.85)
    semantic_edges["SIMILAR_TO (V1 Entity↔Entity)"] = count_query(session, '''
        MATCH ()-[r:SIMILAR_TO {group_id: $gid}]-()
        RETURN count(r) as count
    ''', gid=group_id)

    # V2: SEMANTICALLY_SIMILAR — Section ↔ Section (pipeline-created)
    semantic_edges["SEMANTICALLY_SIMILAR (Section↔Section)"] = count_query(session, '''
        MATCH (s1:Section {group_id: $gid})-[r:SEMANTICALLY_SIMILAR]->(s2:Section)
        RETURN count(r) as count
    ''', gid=group_id)

    # V2: SEMANTICALLY_SIMILAR — GDS KNN (all node types)
    semantic_edges["SEMANTICALLY_SIMILAR (GDS KNN, all)"] = count_query(session, '''
        MATCH ()-[r:SEMANTICALLY_SIMILAR {group_id: $gid}]-()
        RETURN count(r) as count
    ''', gid=group_id)

    # Breakdown by method if GDS edges exist
    gds_knn_count = count_query(session, '''
        MATCH ()-[r:SEMANTICALLY_SIMILAR {group_id: $gid, method: 'gds_knn'}]-()
        RETURN count(r) as count
    ''', gid=group_id)
    if gds_knn_count > 0:
        semantic_edges["  └─ via GDS KNN"] = gds_knn_count

    report["semantic_edges"] = semantic_edges

    # ──────────────────────────────────────────────────────────────────
    # 7. DI METADATA EDGES (Barcode, Figure, KeyValuePair)
    # ──────────────────────────────────────────────────────────────────
    di_edges = OrderedDict()

    di_edges["FOUND_IN (Barcode→Doc)"] = count_query(session, '''
        MATCH (b:Barcode {group_id: $gid})-[r:FOUND_IN]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    di_edges["FOUND_IN (Figure→Doc)"] = count_query(session, '''
        MATCH (f:Figure {group_id: $gid})-[r:FOUND_IN]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    di_edges["FOUND_IN (KeyValuePair→Doc)"] = count_query(session, '''
        MATCH (kvp:KeyValuePair {group_id: $gid})-[r:FOUND_IN]->(d:Document)
        RETURN count(r) as count
    ''', gid=group_id)

    report["di_metadata_edges"] = di_edges

    # ──────────────────────────────────────────────────────────────────
    # 8. COMMUNITY / GDS PROPERTIES
    # ──────────────────────────────────────────────────────────────────
    gds_props = OrderedDict()

    # community_id on Entities
    entities_with_community = count_query(session, '''
        MATCH (e:Entity {group_id: $gid})
        WHERE e.community_id IS NOT NULL AND e.community_id > 0
        RETURN count(e) as count
    ''', gid=group_id)
    gds_props["Entities with community_id"] = f"{entities_with_community}/{nodes['Entity']}"
    if nodes["Entity"] > 0 and entities_with_community == 0:
        issues.append("No Entities have community_id (GDS Louvain not run)")

    # pagerank on Entities
    entities_with_pagerank = count_query(session, '''
        MATCH (e:Entity {group_id: $gid})
        WHERE e.pagerank IS NOT NULL AND e.pagerank > 0
        RETURN count(e) as count
    ''', gid=group_id)
    gds_props["Entities with pagerank"] = f"{entities_with_pagerank}/{nodes['Entity']}"
    if nodes["Entity"] > 0 and entities_with_pagerank == 0:
        issues.append("No Entities have pagerank (GDS PageRank not run)")

    # importance_score / degree / chunk_count
    entities_with_importance = count_query(session, '''
        MATCH (e:Entity {group_id: $gid})
        WHERE e.importance_score IS NOT NULL
        RETURN count(e) as count
    ''', gid=group_id)
    gds_props["Entities with importance_score"] = f"{entities_with_importance}/{nodes['Entity']}"

    # BELONGS_TO (Entity → Community)
    gds_props["BELONGS_TO (Entity→Community)"] = count_query(session, '''
        MATCH (e:Entity {group_id: $gid})-[r:BELONGS_TO]->(c:Community)
        RETURN count(r) as count
    ''', gid=group_id)

    report["gds_properties"] = gds_props

    # ──────────────────────────────────────────────────────────────────
    # 9. EMBEDDINGS
    # ──────────────────────────────────────────────────────────────────
    embeddings = OrderedDict()

    # TextChunk embeddings
    tc_v2 = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid}) WHERE c.embedding_v2 IS NOT NULL
        RETURN count(c) as count
    ''', gid=group_id)
    tc_v1 = count_query(session, '''
        MATCH (c:TextChunk {group_id: $gid}) WHERE c.embedding IS NOT NULL
        RETURN count(c) as count
    ''', gid=group_id)
    embeddings["TextChunk embedding_v2"] = f"{tc_v2}/{nodes['TextChunk']} ({pct(tc_v2, nodes['TextChunk'])})"
    embeddings["TextChunk embedding (v1)"] = f"{tc_v1}/{nodes['TextChunk']} ({pct(tc_v1, nodes['TextChunk'])})"

    # V2 dimension check
    if tc_v2 > 0:
        result = session.run('''
            MATCH (c:TextChunk {group_id: $gid}) WHERE c.embedding_v2 IS NOT NULL
            RETURN size(c.embedding_v2) as dim LIMIT 1
        ''', gid=group_id)
        dim = result.single()["dim"]
        embeddings["TextChunk V2 dim"] = f"{dim} (expected: 2048)"
        if dim != 2048:
            issues.append(f"TextChunk V2 embedding dimension {dim} != 2048")

    # Section embeddings
    sec_emb = count_query(session, '''
        MATCH (s:Section {group_id: $gid}) WHERE s.embedding IS NOT NULL
        RETURN count(s) as count
    ''', gid=group_id)
    embeddings["Section embedding"] = f"{sec_emb}/{nodes['Section']} ({pct(sec_emb, nodes['Section'])})"
    if nodes["Section"] > 0 and sec_emb == 0:
        issues.append("No Sections have embeddings (section embedding step failed)")

    # Entity embeddings
    ent_v2 = count_query(session, '''
        MATCH (e:Entity {group_id: $gid}) WHERE e.embedding_v2 IS NOT NULL
        RETURN count(e) as count
    ''', gid=group_id)
    ent_v1 = count_query(session, '''
        MATCH (e:Entity {group_id: $gid}) WHERE e.embedding IS NOT NULL
        RETURN count(e) as count
    ''', gid=group_id)
    embeddings["Entity embedding_v2"] = f"{ent_v2}/{nodes['Entity']}"
    embeddings["Entity embedding (v1)"] = f"{ent_v1}/{nodes['Entity']}"

    # KeyValue key_embedding
    kv_emb = count_query(session, '''
        MATCH (kv:KeyValue {group_id: $gid}) WHERE kv.key_embedding IS NOT NULL
        RETURN count(kv) as count
    ''', gid=group_id)
    embeddings["KeyValue key_embedding"] = f"{kv_emb}/{nodes['KeyValue']}"
    if nodes["KeyValue"] > 0 and kv_emb == 0:
        issues.append("No KeyValues have key_embedding")

    # KeyValuePair embedding_v2
    kvp_emb = count_query(session, '''
        MATCH (kvp:KeyValuePair {group_id: $gid}) WHERE kvp.embedding_v2 IS NOT NULL
        RETURN count(kvp) as count
    ''', gid=group_id)
    embeddings["KeyValuePair embedding_v2"] = f"{kvp_emb}/{nodes['KeyValuePair']}"

    # Figure embedding_v2
    fig_emb = count_query(session, '''
        MATCH (f:Figure {group_id: $gid}) WHERE f.embedding_v2 IS NOT NULL
        RETURN count(f) as count
    ''', gid=group_id)
    embeddings["Figure embedding_v2"] = f"{fig_emb}/{nodes['Figure']}"

    report["embeddings"] = embeddings

    # ──────────────────────────────────────────────────────────────────
    # 10. ENTITY ALIASES
    # ──────────────────────────────────────────────────────────────────
    aliases_info = OrderedDict()
    with_aliases = count_query(session, '''
        MATCH (e:Entity {group_id: $gid})
        WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
        RETURN count(e) as count
    ''', gid=group_id)
    aliases_info["Entities with aliases"] = f"{with_aliases}/{nodes['Entity']} ({pct(with_aliases, nodes['Entity'])})"

    if with_aliases > 0 and not args.json:
        result = session.run('''
            MATCH (e:Entity {group_id: $gid})
            WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
            RETURN e.name as name, e.aliases as aliases
            LIMIT 5
        ''', gid=group_id)
        samples = []
        for record in result:
            aliases_str = ", ".join(record['aliases'][:3])
            if len(record['aliases']) > 3:
                aliases_str += f" (+{len(record['aliases']) - 3} more)"
            samples.append(f"{record['name']} → [{aliases_str}]")
        aliases_info["samples"] = samples

    report["entity_aliases"] = aliases_info

    # ──────────────────────────────────────────────────────────────────
    # 11. LANGUAGE SPANS ON DOCUMENTS
    # ──────────────────────────────────────────────────────────────────
    lang_info = OrderedDict()
    docs_with_lang = count_query(session, '''
        MATCH (d:Document {group_id: $gid})
        WHERE d.language_spans IS NOT NULL
        RETURN count(d) as count
    ''', gid=group_id)
    lang_info["Documents with language_spans"] = f"{docs_with_lang}/{nodes['Document']}"
    if nodes["Document"] > 0 and docs_with_lang < nodes["Document"]:
        issues.append(f"Only {docs_with_lang}/{nodes['Document']} Documents have language_spans")

    # Also check primary_language and detected_languages
    docs_with_primary = count_query(session, '''
        MATCH (d:Document {group_id: $gid})
        WHERE d.primary_language IS NOT NULL
        RETURN count(d) as count
    ''', gid=group_id)
    lang_info["Documents with primary_language"] = f"{docs_with_primary}/{nodes['Document']}"

    report["language_spans"] = lang_info

    # ──────────────────────────────────────────────────────────────────
    # 12. DOCUMENT LIST
    # ──────────────────────────────────────────────────────────────────
    result = session.run('''
        MATCH (d:Document {group_id: $gid})
        RETURN d.title as title, d.language_spans IS NOT NULL as has_lang,
               d.primary_language as lang
        ORDER BY d.title
    ''', gid=group_id)
    docs = []
    for record in result:
        docs.append({
            "title": record["title"],
            "has_language_spans": record["has_lang"],
            "primary_language": record["lang"],
        })
    report["documents"] = docs

    report["issues"] = issues
    return report


def print_report(report, group_id):
    """Pretty-print the validation report."""
    print(f"\n{'#' * 70}")
    print(f"  Graph Validation Report — group: {group_id}")
    print(f"{'#' * 70}")

    # Nodes
    section_header("Node Counts")
    for label, count in report["nodes"].items():
        marker = "  " if count > 0 else "⚠ "
        print(f"  {marker}{label:20s} {count}")

    # Structural edges
    section_header("Structural Edges (Document ↔ Section ↔ TextChunk)")
    for edge_type, count in report["structural_edges"].items():
        print(f"  {edge_type:45s} {count}")
    print(f"\n  Orphan Sections (unreachable): {report['orphan_sections']}")

    # Entity / Knowledge edges
    section_header("Entity / Knowledge Edges")
    for edge_type, count in report["entity_edges"].items():
        print(f"  {edge_type:45s} {count}")

    # Foundation edges
    section_header("Phase 1: Foundation Edges")
    for edge_type, count in report["foundation_edges"].items():
        print(f"  {edge_type:45s} {count}")

    # Connectivity edges
    section_header("Phase 2: Connectivity Edges")
    for edge_type, count in report["connectivity_edges"].items():
        print(f"  {edge_type:45s} {count}")

    # Semantic edges
    section_header("Phase 3: Semantic Enhancement Edges")
    for edge_type, count in report["semantic_edges"].items():
        print(f"  {edge_type:45s} {count}")

    # DI metadata edges
    section_header("DI Metadata Edges (Barcode, Figure, KeyValuePair)")
    for edge_type, count in report["di_metadata_edges"].items():
        print(f"  {edge_type:45s} {count}")

    # GDS properties
    section_header("GDS Properties (Louvain / PageRank)")
    for prop, val in report["gds_properties"].items():
        print(f"  {prop:45s} {val}")

    # Embeddings
    section_header("Embeddings")
    for emb_type, val in report["embeddings"].items():
        print(f"  {emb_type:35s} {val}")

    # Entity aliases
    section_header("Entity Aliases")
    for k, v in report["entity_aliases"].items():
        if k == "samples":
            print("\n  Sample entities with aliases:")
            for s in v:
                print(f"    • {s}")
        else:
            print(f"  {k:35s} {v}")

    # Language spans
    section_header("Language Detection on Documents")
    for k, v in report["language_spans"].items():
        print(f"  {k:45s} {v}")

    # Documents
    section_header("Documents")
    print(f"  Total: {len(report['documents'])}")
    for doc in report["documents"]:
        lang_icon = status_icon(doc["has_language_spans"])
        lang_str = f" [{doc['primary_language']}]" if doc["primary_language"] else ""
        print(f"  {lang_icon} {doc['title']}{lang_str}")

    # Summary
    section_header("VALIDATION SUMMARY")
    if report["issues"]:
        print(f"  {status_icon(False)} {len(report['issues'])} issue(s) found:\n")
        for i, issue in enumerate(report["issues"], 1):
            print(f"    {i}. {issue}")
    else:
        print(f"  {status_icon(True)} All checks passed — graph looks healthy!")

    print()


def main():
    parser = argparse.ArgumentParser(description="Validate LazyGraphRAG indexed graph")
    parser.add_argument("group_id", nargs="?", default=None, help="group_id to check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--quick", action="store_true", help="Only node counts + edge counts")
    parser.add_argument("--expected-docs", type=int, default=None, help="Expected number of documents")
    parser.add_argument("--uri", default=None, help="Neo4j URI override")
    parser.add_argument("--user", default=None, help="Neo4j username override")
    parser.add_argument("--password", default=None, help="Neo4j password override")
    args = parser.parse_args()

    # Resolve group_id
    group_id = args.group_id
    if not group_id:
        try:
            with open("last_test_group_id.txt") as f:
                group_id = f.read().strip()
            print(f"Using group ID from last_test_group_id.txt: {group_id}")
        except FileNotFoundError:
            group_id = "test-5pdfs-v2-fix2"
            print(f"Using default group ID: {group_id}")

    # Resolve Neo4j credentials
    uri = args.uri or os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
    username = args.user or os.getenv("NEO4J_USERNAME", "neo4j")
    password = args.password or os.getenv("NEO4J_PASSWORD")

    if not password:
        print("ERROR: NEO4J_PASSWORD environment variable not set (or use --password)")
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(username, password))

    try:
        with driver.session(database="neo4j") as session:
            report = build_report(session, group_id, args)

            if args.json:
                print(json.dumps({"group_id": group_id, **report}, indent=2, default=str))
            else:
                print_report(report, group_id)

            # Exit code: 1 if issues found
            if report["issues"]:
                sys.exit(1)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
