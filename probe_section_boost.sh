#!/bin/bash
# Quick probe to validate section_boost deployment

python3 <<'PY'
import requests, json, sys

BASE='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'
GROUP='test-5pdfs-1767429340223041632'

def run(q):
    r = requests.post(
        f"{BASE}/hybrid/query",
        headers={"X-Group-ID": GROUP, "Content-Type": "application/json"},
        json={'query': q, 'response_type': 'summary', 'force_route': 'global_search'},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()

questions = [
    ('Q-G4', 'What obligations are explicitly described as reporting / record-keeping?'),
    ('Q-G5', 'What remedies / dispute-resolution mechanisms are described?'),
]

for label, q in questions:
    print(f"\n{'='*70}\n{label}: {q}\n{'='*70}")
    sys.stdout.flush()
    try:
        data = run(q)
        meta = data.get('metadata', {})
        
        print(f"\n✓ route_used: {data.get('route_used')}")
        print(f"✓ text_chunks_used: {meta.get('text_chunks_used')}")
        
        kb = meta.get('keyword_boost', {})
        print(f"\nkeyword_boost:")
        print(f"  enabled: {kb.get('enabled')}")
        print(f"  applied: {kb.get('applied')}")
        print(f"  profiles: {kb.get('profiles')}")
        print(f"  boost_added: {kb.get('boost_added')}")
        
        sb = meta.get('section_boost', {})
        print(f"\nsection_boost:")
        print(f"  enabled: {sb.get('enabled')}")
        print(f"  applied: {sb.get('applied')}")
        print(f"  profiles: {sb.get('profiles')}")
        print(f"  boost_added: {sb.get('boost_added')}")
        
        citations = data.get('citations', [])
        print(f"\ncitations: {len(citations)} total")
        
        if label == 'Q-G4':
            terms = ['monthly statement', 'income', 'expenses', 'volumes', 'pumper', 'county']
            print(f"\nQ-G4 term coverage:")
            found_count = 0
            for term in terms:
                found = any(term.lower() in (c.get('text_preview', '') or '').lower() for c in citations)
                print(f"  {term:20} {'✓' if found else '✗'}")
                if found:
                    found_count += 1
            print(f"\n→ Q-G4 score: {found_count}/6")
        
        if label == 'Q-G5':
            terms = ['arbitration', 'binding', 'small claims', 'legal fees', 'contractor', 'default']
            print(f"\nQ-G5 term coverage:")
            found_count = 0
            for term in terms:
                found = any(term.lower() in (c.get('text_preview', '') or '').lower() for c in citations)
                print(f"  {term:20} {'✓' if found else '✗'}")
                if found:
                    found_count += 1
            print(f"\n→ Q-G5 score: {found_count}/6")
    
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

print(f"\n{'='*70}\nProbe complete. If section_boost.applied=True and term scores improved,\ndeployment is successful.\n{'='*70}\n")
PY
