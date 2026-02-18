"""Analyze which sentences are dropped by the min-word filter at different thresholds.

Pulls TextChunk texts from Neo4j, runs spaCy sentence extraction, and reports 
which sentences would be kept/dropped at thresholds 3, 4, and 5 words.
"""
import os
import re
import sys

# Load .env.local
from pathlib import Path
env_path = Path(__file__).resolve().parent.parent / ".env.local"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neo4j import GraphDatabase

URI = os.environ["NEO4J_URI"]
USER = os.environ["NEO4J_USERNAME"]  
PASSWORD = os.environ["NEO4J_PASSWORD"]
GROUP_ID = "test-5pdfs-v2-fix2"

# Import noise detection from our service
from src.worker.services.sentence_extraction_service import (
    _is_noise_sentence,
    _is_kvp_label,
    _clean_chunk_text_for_spacy,
    KVP_PATTERN_RE,
    ALL_CAPS_RE,
)


def get_chunks_from_neo4j():
    """Pull all TextChunk texts for the group."""
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session() as session:
        result = session.run(
            "MATCH (c:TextChunk {group_id: $gid}) "
            "RETURN c.id AS id, c.text AS text, c.document_id AS doc_id "
            "ORDER BY c.document_id, c.id",
            gid=GROUP_ID,
        )
        chunks = [dict(r) for r in result]
    driver.close()
    return chunks


def analyze_sentences(chunks):
    """Extract all sentences and categorize by threshold behavior."""
    import spacy
    nlp = spacy.load("en_core_web_sm")
    nlp.max_length = 50_000

    all_sentences = []

    for chunk in chunks:
        clean_text = _clean_chunk_text_for_spacy(chunk["text"])
        if not clean_text:
            continue
        doc = nlp(clean_text)
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            word_count = len(sent_text.split())
            char_count = len(sent_text)
            # Check each filter independently
            cleaned_alpha = re.sub(r"[\d,.$%\s\-/·•]", "", sent_text)
            
            filters = {
                "min_chars_30": char_count < 30,
                "kvp_pattern": bool(KVP_PATTERN_RE.match(sent_text)),
                "all_caps_short": bool(ALL_CAPS_RE.match(sent_text)) and word_count < 10,
                "numeric_only": len(cleaned_alpha) < 10,
            }
            
            all_sentences.append({
                "text": sent_text,
                "words": word_count,
                "chars": char_count,
                "alpha_chars": len(cleaned_alpha),
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["id"],
                "filters": filters,
                "kvp_label": _is_kvp_label(sent_text),
            })

    return all_sentences


def main():
    print("Fetching chunks from Neo4j...")
    chunks = get_chunks_from_neo4j()
    print(f"  Found {len(chunks)} TextChunks for group {GROUP_ID}")
    
    print("\nExtracting sentences with spaCy...")
    sentences = analyze_sentences(chunks)
    print(f"  Extracted {len(sentences)} raw sentences")
    
    # Separate sentences that are already filtered by non-word-count filters
    other_filtered = [s for s in sentences if any(s["filters"].values()) or s["kvp_label"]]
    word_eligible = [s for s in sentences if not any(s["filters"].values()) and not s["kvp_label"]]
    
    print(f"\n  {len(other_filtered)} removed by other filters (chars, KVP, all-caps, numeric)")
    print(f"  {len(word_eligible)} pass all non-word-count filters")
    
    # Now analyze word count distribution of eligible sentences
    print("\n" + "="*80)
    print("WORD COUNT ANALYSIS (sentences that pass all other filters)")
    print("="*80)
    
    for threshold in [3, 4, 5]:
        dropped = [s for s in word_eligible if s["words"] < threshold]
        kept = [s for s in word_eligible if s["words"] >= threshold]
        print(f"\n--- Threshold = {threshold} words ---")
        print(f"  Kept: {len(kept)}, Dropped: {len(dropped)}")
        if dropped:
            print(f"  Dropped sentences:")
            for s in dropped:
                print(f"    [{s['words']}w {s['chars']}c] {s['text'][:120]}")
                print(f"        doc: {s['doc_id'][:40]}  chunk: {s['chunk_id'][:40]}")
    
    # Special focus: sentences with exactly 3-4 words
    print("\n" + "="*80)
    print("FOCUS: Sentences with 3-4 words (dropped at threshold=5, kept at threshold=3)")
    print("="*80)
    short = [s for s in word_eligible if s["words"] in (3, 4)]
    for s in short:
        print(f"\n  [{s['words']} words] \"{s['text']}\"")
        print(f"    doc: {s['doc_id']}")
        print(f"    chars={s['chars']}, alpha={s['alpha_chars']}")
    
    if not short:
        print("  (none)")
    
    # Check: how many currently existing Sentence nodes are there?
    print("\n" + "="*80)
    print("CURRENT SENTENCE NODES IN NEO4J")
    print("="*80)
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session() as session:
        result = session.run(
            "MATCH (s:Sentence {group_id: $gid}) "
            "RETURN count(s) AS cnt",
            gid=GROUP_ID,
        )
        cnt = result.single()["cnt"]
        print(f"  {cnt} Sentence nodes exist for group {GROUP_ID}")
        
        # Check specifically for "forfeited" or "deposit"
        result = session.run(
            "MATCH (s:Sentence {group_id: $gid}) "
            "WHERE s.text CONTAINS 'forfeit' OR s.text CONTAINS 'deposit' "
            "RETURN s.text AS text, s.id AS id",
            gid=GROUP_ID,
        )
        matches = list(result)
        if matches:
            print(f"\n  Sentences containing 'forfeit' or 'deposit':")
            for m in matches:
                print(f"    {m['text'][:120]}")
        else:
            print(f"\n  No Sentence nodes contain 'forfeit' or 'deposit' — confirming the gap")
        
        # Check TextChunks for "forfeited"
        result = session.run(
            "MATCH (c:TextChunk {group_id: $gid}) "
            "WHERE c.text CONTAINS 'forfeit' "
            "RETURN c.id AS id, c.text AS text",
            gid=GROUP_ID,
        )
        matches = list(result)
        if matches:
            print(f"\n  TextChunks containing 'forfeit':")
            for m in matches:
                text = m['text']
                # Show context around "forfeit"
                idx = text.lower().find("forfeit")
                start = max(0, idx - 80)
                end = min(len(text), idx + 80)
                print(f"    ...{text[start:end]}...")
    driver.close()


if __name__ == "__main__":
    main()
