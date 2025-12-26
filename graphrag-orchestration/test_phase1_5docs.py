#!/usr/bin/env python3
"""Test Phase 1 quality metrics with 5 real documents.

Supports:
- Index + wait + Neo4j verification (Phase 1)
- Endpoint-focused engine correctness QA using the grounded question bank
"""

import os
import re
import requests
import time
from dataclasses import dataclass
from pathlib import Path
from neo4j import GraphDatabase

# Configuration
# Allow overriding to test local/staging deployments.
API_URL = os.getenv(
    "API_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
GROUP_ID = os.getenv("GROUP_ID", f"phase1-5docs-{int(time.time())}")  # Unique group ID
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

# Storage Account for managed identity
STORAGE_ACCOUNT = "neo4jstorage21224"
CONTAINER = "test-docs"
PDF_FILES = [
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf"
]

# Optional safety + automation toggles
CLEANUP_ALL_GROUPS = os.getenv("CLEANUP_ALL_GROUPS", "false").lower() == "true"
WAIT_TIMEOUT_SECONDS = int(os.getenv("WAIT_TIMEOUT_SECONDS", "900"))
WAIT_POLL_SECONDS = int(os.getenv("WAIT_POLL_SECONDS", "10"))
RUN_LOCAL_QA = os.getenv("RUN_LOCAL_QA", "false").lower() == "true"
SKIP_INDEXING = os.getenv("SKIP_INDEXING", "false").lower() == "true"
SKIP_NEO4J_VERIFY = os.getenv("SKIP_NEO4J_VERIFY", "false").lower() == "true"
LOCAL_QUERY_TIMEOUT_SECONDS = int(os.getenv("LOCAL_QUERY_TIMEOUT_SECONDS", "240"))
LOCAL_QUERY_RETRIES = int(os.getenv("LOCAL_QUERY_RETRIES", "2"))
SLEEP_BETWEEN_QUERIES_SECONDS = float(os.getenv("SLEEP_BETWEEN_QUERIES_SECONDS", "2"))
QA_ENGINES = [e.strip().lower() for e in os.getenv("QA_ENGINES", "").split(",") if e.strip()]
QA_FAIL_FAST = os.getenv("QA_FAIL_FAST", "false").lower() == "true"
QA_PRINT_ANSWERS = os.getenv("QA_PRINT_ANSWERS", "false").lower() == "true"
QA_PRINT_SOURCES = os.getenv("QA_PRINT_SOURCES", "false").lower() == "true"

# Question bank driven endpoint QA
RUN_QUESTION_BANK = os.getenv("RUN_QUESTION_BANK", "false").lower() == "true"
QUESTION_BANK_PATH = os.getenv("QUESTION_BANK_PATH", "../QUESTION_BANK_5PDFS_2025-12-24.md")
QA_INCLUDE_NEGATIVES = os.getenv("QA_INCLUDE_NEGATIVES", "true").lower() == "true"


def _resolve_input_path(path: str) -> Path:
    """Resolve a user-provided path robustly.

    The harness is often run from repo root, but the default QUESTION_BANK_PATH is
    relative to this script's directory. Prefer existing paths in this order:
    1) as provided (absolute or relative to CWD)
    2) relative to this script directory
    """
    raw = (path or "").strip()
    if not raw:
        return Path(raw)

    p = Path(raw)
    if p.exists():
        return p

    script_dir = Path(__file__).resolve().parent
    p2 = (script_dir / p).resolve()
    if p2.exists():
        return p2

    # Helpful error message with candidates.
    candidates = [p.resolve(), p2]
    details = "\n".join(f"- {c}" for c in candidates)
    raise FileNotFoundError(f"Path not found: {raw}\nTried:\n{details}")


def _sleep_with_notice(seconds: float, reason: str) -> None:
    if seconds <= 0:
        return
    print(f"  ⏳ {reason} (sleep {seconds:.0f}s)")
    time.sleep(seconds)


def _post_with_rate_limit_retry(url: str, *, json_body: dict, timeout_seconds: int) -> requests.Response:
    """POST with retries and 429 handling.

    - Retries network errors.
    - On HTTP 429, honors Retry-After if present.
    """
    last_exc: Exception | None = None
    for attempt in range(LOCAL_QUERY_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                json=json_body,
                headers={"X-Group-ID": GROUP_ID},
                timeout=timeout_seconds,
            )

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.strip().isdigit():
                    wait_s = float(retry_after.strip())
                else:
                    wait_s = float(10 * (attempt + 1))
                _sleep_with_notice(wait_s, "Rate limited (429)")
                continue

            return resp

        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt >= LOCAL_QUERY_RETRIES:
                raise
            backoff = float(5 * (attempt + 1))
            _sleep_with_notice(backoff, f"Request error: {e}")

    # Should be unreachable, but keep mypy/humans happy
    if last_exc:
        raise last_exc
    raise RuntimeError("POST failed without response")


def _extract_answer_and_search_type(resp: requests.Response) -> tuple[str, str]:
    try:
        data = resp.json()
    except Exception:
        return (resp.text or ""), ""
    return (data.get("answer") or ""), (data.get("search_type") or "")


def _extract_sources(resp: requests.Response) -> list[dict]:
    try:
        data = resp.json()
    except Exception:
        return []
    sources = data.get("sources")
    if isinstance(sources, list):
        return [s for s in sources if isinstance(s, dict)]
    return []


def _print_sources(sources: list[dict], *, max_items: int = 5) -> None:
    if not sources:
        print("  ↳ Sources: (none)")
        return
    print(f"  ↳ Sources (showing up to {max_items}):")
    for idx, s in enumerate(sources[:max_items], start=1):
        sid = str(s.get("id", ""))
        name = str(s.get("name", ""))
        stype = str(s.get("type", ""))
        doc_id = str(s.get("document_id", ""))
        score = s.get("score", "")

        label_bits = []
        if name:
            label_bits.append(name)
        if stype:
            label_bits.append(f"type={stype}")
        if doc_id:
            label_bits.append(f"document_id={doc_id}")
        if sid:
            label_bits.append(f"id={sid}")
        if score != "":
            try:
                label_bits.append(f"score={float(score):.3f}")
            except Exception:
                label_bits.append(f"score={score}")

        print(f"    {idx}. " + (" | ".join(label_bits) if label_bits else "(unlabeled source)"))

        # Some routes may include text/excerpts in the source object.
        excerpt = s.get("text") or s.get("excerpt") or s.get("content")
        if isinstance(excerpt, str) and excerpt.strip():
            ex = excerpt.strip().replace("\n", " ")
            print(f"       excerpt: {ex[:240]}")


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str
    expected_text: str
    source_text: str


def _normalize_text(s: str) -> str:
    return re.sub(r"[^a-z0-9@]+", "", (s or "").lower())


def _term_in_answer(term: str, answer: str) -> bool:
    a = _normalize_text(answer)
    for v in _term_variants(term):
        tv = _normalize_text(v)
        if not tv:
            return True
        if tv in a:
            return True
    return False


_MONTHS = {
    1: ["january", "jan"],
    2: ["february", "feb"],
    3: ["march", "mar"],
    4: ["april", "apr"],
    5: ["may"],
    6: ["june", "jun"],
    7: ["july", "jul"],
    8: ["august", "aug"],
    9: ["september", "sep", "sept"],
    10: ["october", "oct"],
    11: ["november", "nov"],
    12: ["december", "dec"],
}


def _term_variants(term: str) -> list[str]:
    """Generate looser matching variants for a required term.

    This harness is intended to validate correctness, not formatting.
    """
    t = (term or "").strip()
    if not t:
        return [""]

    variants: list[str] = [t]

    # ISO date -> common formats (MM/DD/YYYY and Month DD, YYYY)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        variants.append(f"{month:02d}/{day:02d}/{year}")
        variants.append(f"{month}/{day}/{year}")
        for name in _MONTHS.get(month, []):
            variants.append(f"{name} {day}, {year}")
            variants.append(f"{name} {day} {year}")

    # If term contains a percentage, allow numeric-only variants.
    pct_paren = re.search(r"\(\s*(\d{1,3})\s*%\s*\)", t)
    if pct_paren:
        n = pct_paren.group(1)
        variants.extend([f"{n}%", f"{n} percent", n])
    else:
        pct = re.search(r"\b(\d{1,3})\s*%\b", t)
        if pct:
            n = pct.group(1)
            variants.extend([f"{n}%", f"{n} percent", n])

    # Money: allow matching just the amount.
    money = re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)", t)
    if money:
        amt = money.group(1)
        variants.extend([f"${amt}", amt])

    # Monthly phrasing: "/month" <-> "per month"
    if "/month" in t.lower():
        variants.append(re.sub(r"(?i)/month", " per month", t))
    if "per month" in t.lower():
        variants.append(re.sub(r"(?i)per month", "/month", t))

    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        key = _normalize_text(v)
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _extract_required_terms(expected_text: str) -> list[str]:
    """Extract match terms from the question bank expected text.

    Preference order:
    - backtick terms (most precise)
    - dates ($mm/dd/yyyy$, $yyyy-mm-dd$)
    - money/number tokens
    """
    text = expected_text or ""

    terms: list[str] = []

    # Backticks are the strongest anchors in the markdown question bank.
    for bt in re.findall(r"`([^`]+)`", text):
        for part in bt.split(";"):
            p = part.strip()
            if p:
                terms.append(p)

    # Dates
    mmddyyyy_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)
    iso_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    terms.extend(mmddyyyy_dates)
    terms.extend(iso_dates)

    # If we have explicit dates, avoid also requiring their individual numeric parts
    # (e.g. "06" from "2010-06-15"), since answers may use month names.
    date_parts_to_skip: set[str] = set()
    for d in iso_dates:
        m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", d)
        if m:
            date_parts_to_skip.add(m.group(1))
            date_parts_to_skip.add(m.group(2))
    for d in mmddyyyy_dates:
        m = re.fullmatch(r"(\d{2})/(\d{2})/\d{4}", d)
        if m:
            date_parts_to_skip.add(m.group(1))
            date_parts_to_skip.add(m.group(2))

    # Codes like REG-54321
    terms.extend(re.findall(r"\b[A-Z]{2,}-\d{3,}\b", text))

    # Currency / numeric anchors
    for num in re.findall(r"\$?\d[\d,]*(?:\.\d+)?", text):
        n = num.strip()
        if not n:
            continue
        if len(n) <= 2 and n.isdigit() and n in date_parts_to_skip:
            continue
        # Drop lone years that may appear in explanatory sentences
        if re.fullmatch(r"\d{4}", n):
            continue
        terms.append(n)

    # Deduplicate, preserve order
    seen = set()
    out: list[str] = []
    for t in terms:
        key = _normalize_text(t)
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _load_question_bank(path: str) -> dict[str, list[BankQuestion]]:
    p = _resolve_input_path(path)

    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    section = None
    sections: dict[str, list[BankQuestion]] = {
        "vector": [],
        "local": [],
        "global": [],
        "drift": [],
        "raptor": [],
        "negative": [],
    }

    # Map markdown section headers to keys
    def _section_key(header_line: str) -> str | None:
        hl = header_line.lower()
        if hl.startswith("## a)") and "vector" in hl:
            return "vector"
        if hl.startswith("## b)") and "local" in hl:
            return "local"
        if hl.startswith("## c)") and "global" in hl:
            return "global"
        if hl.startswith("## d)") and "drift" in hl:
            return "drift"
        if hl.startswith("## e)") and "raptor" in hl:
            return "raptor"
        if hl.startswith("## f)") and "negative" in hl:
            return "negative"
        return None

    # Question IDs in the bank are like: Q-V1, Q-L10, Q-G3, Q-D7, Q-R2, Q-N10
    q_re = re.compile(r"^\s*\d+\.\s*\*\*(Q-[A-Z]-?\d+):\*\*\s*(.+?)\s*$")

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("## "):
            sk = _section_key(line)
            if sk:
                section = sk
            i += 1
            continue

        m = q_re.match(line)
        if not m or section is None:
            i += 1
            continue

        qid = m.group(1).strip()
        query = m.group(2).strip()
        expected_lines: list[str] = []
        source_text = ""

        j = i + 1
        while j < len(lines):
            s = lines[j].strip()

            # Stop at next question or section
            if s.startswith("## ") or q_re.match(lines[j]):
                break

            if s.startswith("- **Expected:**"):
                remainder = s.split("**Expected:**", 1)[1].strip()
                if remainder:
                    expected_lines.append(remainder)
                j += 1
                while j < len(lines):
                    ss = lines[j].strip()
                    if ss.startswith("- **Source:**") or ss.startswith("## ") or q_re.match(lines[j]):
                        break
                    if ss.startswith("-"):
                        expected_lines.append(ss.lstrip("-").strip())
                    elif ss:
                        expected_lines.append(ss)
                    j += 1
                continue

            if s.startswith("- **Source:**"):
                source_text = s.split("**Source:**", 1)[1].strip()
                j += 1
                continue

            j += 1

        sections[section].append(
            BankQuestion(
                qid=qid,
                query=query,
                expected_text="\n".join(expected_lines).strip(),
                source_text=source_text,
            )
        )

        i = j

    return sections


def _is_negative_ok(answer: str) -> bool:
    # NOTE: This is intentionally heuristic and language-inclusive.
    # For CI stability, prefer deterministic canonical outputs (e.g. forcing a single
    # "Not specified in the provided documents." phrase) and keep this as a safety net.
    a = (answer or "").lower()
    # Normalize formatting that often appears in model output.
    # - Markdown emphasis can split markers: "does **not provide**".
    # - Newlines / double spaces can split markers.
    a = a.replace("\u00a0", " ")
    a = re.sub(r"[*_`]+", "", a)
    a = re.sub(r"\s+", " ", a).strip()

    markers = [
        # EN
        "not specified",
        "not provided",
        "not mentioned",
        "not found",
        "cannot determine",
        "no relevant",
        "not stated",
        "none",
        "not shown",
        "not listed",
        "does not list",
        "does not contain",
        "no clause",
        "does not provide",
        "does not specify",
        "not included",
        "not available",
        "no instructions",
        "no wire",
        "no ach",
        "not specified in the provided documents",

        # DE
        "nicht angegeben",
        "nicht spezifiziert",
        "nicht erwähnt",
        "nicht gefunden",
        "nicht verfügbar",
        "kann nicht bestimmt",
        "kann nicht festgestellt",
        "keine angaben",
        "nicht enthalten",
        "wird nicht bereitgestellt",

        # FR
        "non spécifié",
        "non specifie",  # fallback without accents
        "non indiqué",
        "non indique",
        "non mentionné",
        "non mentionne",
        "introuvable",
        "pas fourni",
        "n'est pas fourni",
        "ne peut pas déterminer",
        "ne peut pas determiner",
        "aucune information",
        "non disponible",

        # ES
        "no se especifica",
        "no especificado",
        "no se menciona",
        "no mencionado",
        "no se encuentra",
        "no encontrado",
        "no proporcionado",
        "no disponible",
        "no incluye",

        # ZH (CN)
        "未提及",
        "未说明",
        "未說明",
        "未指定",
        "未提供",
        "未找到",
        "无法确定",
        "無法確定",
        "没有提到",
        "沒有提到",
        "文档中未",
        "文件中未",
        "资料中没有",
        "資料中沒有",

        # JA (JP)
        "記載されていません",
        "明記されていません",
        "言及されていません",
        "見つかりません",
        "提供されていません",
        "確認できません",
        "不明",

        # KO (KR)
        "명시되어 있지 않습니다",
        "기재되어 있지 않습니다",
        "언급되지 않습니다",
        "찾을 수 없습니다",
        "제공되지 않습니다",
        "확인할 수 없습니다",
        "알 수 없습니다",

        # TH
        "ไม่ระบุ",
        "ไม่ได้ระบุ",
        "ไม่พบ",
        "ไม่มีข้อมูล",
        "ไม่กล่าวถึง",
        "ไม่ปรากฏ",
        "ไม่สามารถระบุได้",
    ]

    if any(m in a for m in markers):
        return True

    # Regex fallbacks for split words / minor punctuation variance.
    regexes = [
        r"\bdoes\s+not\s+provide\b",
        r"\bdoes\s+not\s+specify\b",
        r"\bdoes\s+not\s+list\b",
        r"\bdoes\s+not\s+contain\b",
        r"\bno\s+[^.]{0,40}\s+appears\b",
        r"^none\b",
    ]
    return any(re.search(rx, a) for rx in regexes)


def run_question_bank_engine(engine: str, bank: dict[str, list[BankQuestion]]) -> bool:
    engine = engine.strip().lower()
    if engine not in {"vector", "local", "global", "drift", "raptor"}:
        raise ValueError(f"Unsupported engine: {engine}")

    positives = bank.get(engine, [])
    negatives = bank.get("negative", []) if QA_INCLUDE_NEGATIVES else []

    if len(positives) != 10:
        raise RuntimeError(f"Question bank for {engine} must have 10 questions; found {len(positives)}")
    if QA_INCLUDE_NEGATIVES and len(negatives) != 10:
        raise RuntimeError(f"Question bank negatives must have 10 questions; found {len(negatives)}")

    print("\n" + "=" * 80)
    print(f"QUESTION BANK QA: {engine.upper()} (10 + negatives={QA_INCLUDE_NEGATIVES})")
    print("=" * 80)

    if engine == "vector":
        endpoint = f"{API_URL}/graphrag/v3/query"
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True, "force_route": "vector"}
        expected_search_type = "vector"
    elif engine == "local":
        endpoint = f"{API_URL}/graphrag/v3/query/local"
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True}
        expected_search_type = "local"
    elif engine == "global":
        endpoint = f"{API_URL}/graphrag/v3/query/global"
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True}
        expected_search_type = "global"
    elif engine == "raptor":
        endpoint = f"{API_URL}/graphrag/v3/query/raptor"
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True}
        expected_search_type = "raptor"
    else:  # drift
        endpoint = f"{API_URL}/graphrag/v3/query/drift"
        make_payload = lambda q: {
            "query": q,
            "max_iterations": 5,
            "convergence_threshold": 0.8,
            "include_reasoning_path": False,
        }
        expected_search_type = "drift"

    failures = 0

    def _run_one(q: BankQuestion, *, is_negative: bool) -> bool:
        nonlocal failures
        print(f"\n{q.qid}: {q.query}")
        try:
            resp = _post_with_rate_limit_retry(
                endpoint,
                json_body=make_payload(q.query),
                timeout_seconds=LOCAL_QUERY_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Request failed after retries: {e}")
            failures += 1
            return False

        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}")
            print((resp.text or "")[:1000])
            failures += 1
            return False

        answer, search_type = _extract_answer_and_search_type(resp)
        sources = _extract_sources(resp)
        if not answer.strip():
            print("  ❌ Empty answer")
            if QA_PRINT_SOURCES:
                _print_sources(sources)
            failures += 1
            return False

        if search_type and search_type.lower() != expected_search_type:
            print(f"  ⚠️  Unexpected search_type='{search_type}' (expected '{expected_search_type}')")

        if is_negative:
            if _is_negative_ok(answer):
                print("  ✅ Negative: Pass")
                return True
            print("  ❌ Negative: expected 'not specified/not found' style response")
            if QA_PRINT_ANSWERS:
                print("  ↳ Answer (truncated):")
                print("  " + (answer.strip().replace("\n", "\n  ")[:1200]))
            if QA_PRINT_SOURCES:
                _print_sources(sources)
            failures += 1
            return False

        required = _extract_required_terms(q.expected_text)
        if not required:
            # Fallback: require non-trivial answer.
            if len(answer.strip()) < 40:
                print("  ❌ Answer too short to validate")
                failures += 1
                return False
            print("  ✅ Pass (no explicit required terms found)")
            return True

        missing = [t for t in required if not _term_in_answer(t, answer)]
        if missing:
            print("  ❌ Missing expected terms:", missing[:8])
            if QA_PRINT_ANSWERS:
                print("  ↳ Answer (truncated):")
                print("  " + (answer.strip().replace("\n", "\n  ")[:1200]))
            if QA_PRINT_SOURCES:
                _print_sources(sources)
            failures += 1
            return False

        print("  ✅ Pass")
        return True

    # Positive questions (10)
    for q in positives:
        ok = _run_one(q, is_negative=False)
        if QA_FAIL_FAST and not ok:
            return False
        _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")

    # Negative questions (10) per engine
    if negatives:
        for q in negatives:
            ok = _run_one(q, is_negative=True)
            if QA_FAIL_FAST and not ok:
                return False
            _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")

    if failures:
        print(f"\n⚠️  QUESTION BANK QA ({engine}): {failures} failures")
        return False
    print(f"\n✅ QUESTION BANK QA ({engine}): all passed")
    return True


def run_engine_qa_smoke(engine: str) -> bool:
    """Engine-correctness QA: directly hit per-engine endpoint (no routing).

    This is intentionally small and stable:
    - Confirms endpoint returns HTTP 200
    - Confirms answer is non-empty
    - Optionally checks a few expected terms
    """
    engine = engine.strip().lower()
    if engine not in {"local", "global", "raptor", "drift"}:
        raise ValueError(f"Unsupported engine: {engine}")

    print("\n" + "=" * 80)
    print(f"ENGINE QA: {engine.upper()} ENDPOINT")
    print("=" * 80)

    # Keep these concise to reduce token spend and rate-limit risk.
    if engine == "local":
        endpoint = f"{API_URL}/graphrag/v3/query/local"
        questions: list[tuple[str, list[str]]] = [
            ("Who is the Agent in the property management agreement?", ["Walt Flood Realty"]),
            ("Who is the Owner in the property management agreement?", ["Contoso Ltd"]),
            ("In the purchase contract Exhibit A, what is the job location?", ["811 Ocean Drive", "Tampa"]),
        ]
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True}
    elif engine == "global":
        endpoint = f"{API_URL}/graphrag/v3/query/global"
        questions = [
            (
                "Summarize the documents and mention the main agreements involved.",
                ["agreement", "contract", "invoice"],
            ),
        ]
        make_payload = lambda q: {"query": q, "top_k": 10, "include_sources": True}
    elif engine == "raptor":
        endpoint = f"{API_URL}/graphrag/v3/query/raptor"
        questions = [
            ("What is the total amount due on the Contoso lifts invoice?", ["29,900", "29900"]),
            ("In the purchase contract Exhibit A, what is the contact email?", ["@fabrikam.com", "enolasco"]),
        ]
        make_payload = lambda q: {"query": q, "top_k": 6, "include_sources": True}
    else:  # drift
        endpoint = f"{API_URL}/graphrag/v3/query/drift"
        questions = [
            (
                "Connect the property management agreement parties and the managed property address.",
                ["Contoso", "Honolulu"],
            ),
        ]
        make_payload = lambda q: {
            "query": q,
            "max_iterations": 3,
            "convergence_threshold": 0.8,
            "include_reasoning_path": False,
        }

    failures = 0
    for i, (q, expected_terms) in enumerate(questions, 1):
        print(f"\nQ{i}: {q}")
        try:
            resp = _post_with_rate_limit_retry(
                endpoint,
                json_body=make_payload(q),
                timeout_seconds=LOCAL_QUERY_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Query request failed after retries: {e}")
            failures += 1
            if QA_FAIL_FAST:
                return False
            _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")
            continue

        if resp.status_code != 200:
            print(f"  ❌ Query failed: {resp.status_code}")
            print((resp.text or "")[:1000])
            failures += 1
            if QA_FAIL_FAST:
                return False
            _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")
            continue

        answer, search_type = _extract_answer_and_search_type(resp)
        if not answer.strip():
            print("  ❌ Empty answer")
            failures += 1
            if QA_FAIL_FAST:
                return False
            _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")
            continue

        if search_type and search_type.lower() != engine:
            print(f"  ⚠️  Unexpected search_type='{search_type}' (expected '{engine}')")

        answer_l = answer.lower()
        missing = [t for t in expected_terms if t.lower() not in answer_l]
        if missing:
            print("  ⚠️  Missing expected terms:", missing)
            failures += 1
            if QA_FAIL_FAST:
                return False
        else:
            print("  ✅ Pass")

        _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")

    if failures:
        print(f"\n⚠️  ENGINE QA ({engine}): {failures} failures")
        return False
    print(f"\n✅ ENGINE QA ({engine}): all passed")
    return True

def cleanup_neo4j():
    """Delete all existing groups from Neo4j before starting."""
    print("=" * 80)
    print("CLEANUP: DELETING ALL EXISTING GROUPS FROM NEO4J")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Find all unique group_ids
        result = session.run("""
            MATCH (n)
            WHERE n.group_id IS NOT NULL
            RETURN DISTINCT n.group_id AS group_id
            ORDER BY group_id
        """)
        
        groups = [record['group_id'] for record in result]
        
        if not groups:
            print("✅ No existing groups found - Neo4j is clean")
            driver.close()
            return
        
        print(f"Found {len(groups)} groups to delete")
        
        # Delete all groups
        for group_id in groups:
            result = session.run("""
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                RETURN count(n) AS deleted
            """, group_id=group_id)
            
            record = result.single()
            deleted = record['deleted'] if record else 0
            if deleted > 0:
                print(f"  ✅ Deleted {deleted} nodes from group: {group_id[:40]}...")
    
    print(f"✅ Cleanup complete - deleted {len(groups)} groups\n")
    driver.close()


def wait_for_indexing_completion(*, require_communities: bool = False, require_raptor: bool = False) -> bool:
    """Poll the V3 stats endpoint until indexing is complete (or timeout).

    By default, waits for documents/chunks/entities.
    For global/drift/raptor testing, also wait for communities and/or RAPTOR nodes.
    """
    print("\n" + "=" * 80)
    print("WAIT: POLLING /graphrag/v3/stats UNTIL INDEXING COMPLETES")
    print("=" * 80)

    deadline = time.time() + WAIT_TIMEOUT_SECONDS
    last = None

    while time.time() < deadline:
        try:
            response = requests.get(
                f"{API_URL}/graphrag/v3/stats/{GROUP_ID}",
                headers={"X-Group-ID": GROUP_ID},
                timeout=30,
            )

            if response.status_code != 200:
                print(f"  ⏳ Stats not ready yet ({response.status_code})")
                time.sleep(WAIT_POLL_SECONDS)
                continue

            stats = response.json()
            last = stats
            docs = stats.get("documents", 0)
            chunks = stats.get("text_chunks", 0)
            entities = stats.get("entities", 0)
            communities = stats.get("communities", 0)
            raptor_nodes = stats.get("raptor_nodes", 0)

            print(
                f"  📊 docs={docs} chunks={chunks} entities={entities} communities={communities} raptor={raptor_nodes}"
            )

            # Minimal completion condition (optionally stronger for global/raptor).
            if (
                docs >= len(PDF_FILES)
                and chunks > 0
                and entities > 0
                and (not require_communities or communities > 0)
                and (not require_raptor or raptor_nodes > 0)
            ):
                print("✅ Indexing appears complete")
                return True

        except Exception as e:
            print(f"  ⏳ Stats poll error: {e}")

        time.sleep(WAIT_POLL_SECONDS)

    print("❌ Timed out waiting for indexing completion")
    if last:
        print(f"Last stats: {last}")
    return False


def run_local_qa_smoke() -> bool:
    """Run 10 content-grounded local questions and check key strings."""
    print("\n" + "=" * 80)
    print("PHASE 4: LOCAL QA SMOKE (10 QUESTIONS)")
    print("=" * 80)

    questions = [
        ("Who is the Agent in the property management agreement?", ["Walt Flood Realty"]),
        ("Who is the Owner in the property management agreement?", ["Contoso Ltd"]),
        ("What is the managed property address in the property management agreement?", ["456 Palm Tree Avenue", "Honolulu", "96815"]),
        ("What is the initial term start date in the property management agreement?", ["2010", "06", "15"]),
        ("What written notice period is required for termination of the property management agreement?", ["60", "sixty", "days"]),
        ("What is the Agent fee/commission for short-term rentals (reservations of less than 180 days)?", ["25", "twenty", "percent"]),
        ("What is the Agent fee/commission for long-term leases (leases of more than 180 days)?", ["10", "ten", "percent"]),
        ("What is the pro-ration advertising charge and the minimum admin/accounting charge?", ["75", "50"]),
        ("In the purchase contract Exhibit A, what is the job location?", ["811 Ocean Drive", "Tampa", "33602"]),
        ("In the purchase contract Exhibit A, what is the contact name and email?", ["Elizabeth", "Nolasco", "enolasco@fabrikam.com"]),
    ]

    failures = 0
    for i, (q, expected_terms) in enumerate(questions, 1):
        print(f"\nQ{i}: {q}")
        try:
            resp = _post_with_rate_limit_retry(
                f"{API_URL}/graphrag/v3/query/local",
                json_body={"query": q, "top_k": 10, "include_sources": True},
                timeout_seconds=LOCAL_QUERY_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Query request failed after retries: {e}")
            failures += 1
            _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")
            continue

        if resp.status_code != 200:
            print(f"  ❌ Query failed: {resp.status_code}")
            print((resp.text or "")[:1000])
            failures += 1
            continue

        answer = (resp.json().get("answer") or "")
        answer_l = answer.lower()
        missing = [t for t in expected_terms if t.lower() not in answer_l]
        if missing:
            print("  ⚠️  Missing expected terms:", missing)
            failures += 1
        else:
            print("  ✅ Pass")

        _sleep_with_notice(SLEEP_BETWEEN_QUERIES_SECONDS, "Pacing")

    if failures:
        print(f"\n⚠️  LOCAL QA: {failures} failures")
        return False
    print("\n✅ LOCAL QA: all passed")
    return True

def test_indexing():
    """Index 5 documents using managed identity for blob storage and Document Intelligence."""
    print("=" * 80)
    print("PHASE 1: INDEXING 5 DOCUMENTS WITH MANAGED IDENTITY")
    print("=" * 80)
    
    # Generate blob URLs (no SAS tokens)
    blob_urls = []
    for filename in PDF_FILES:
        url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}/{filename}"
        blob_urls.append(url)
        print(f"   {filename}")
    
    print(f"\n   Total: {len(blob_urls)} PDFs")
    print(f"   Authentication: Managed Identity")
    
    print("\n" + "=" * 80)
    print("PHASE 2: SUBMITTING TO GRAPHRAG V3 API")
    print("=" * 80)
    
    start_time = time.time()
    
    # Index documents
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        json={
            "documents": blob_urls,
            "run_raptor": True,
            "run_community_detection": True,
            "ingestion": "document-intelligence"  # Use DI with managed identity
        },
        headers={"X-Group-ID": GROUP_ID},
        timeout=300
    )
    
    elapsed = time.time() - start_time
    
    if response.status_code != 200:
        print(f"❌ Indexing failed: {response.status_code} after {elapsed:.1f}s")
        print(response.text)
        return False
    
    result = response.json()
    print(f"✅ Indexing request accepted in {elapsed:.1f}s")
    print(f"   Status: {result.get('status', 'unknown')}")
    print(f"   Documents processed: {result.get('documents_processed', 0)}")
    print(f"   Entities created: {result.get('entities_created', 0)}")
    print(f"   Relationships created: {result.get('relationships_created', 0)}")
    print(f"   RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
    print(f"   Message: {result.get('message', '')}")
    
    return True

def verify_quality_metrics():
    """Query Neo4j to verify Phase 1 quality metrics and entity counts."""
    print("\n" + "=" * 80)
    print("PHASE 3: VERIFY DATA AND QUALITY METRICS IN NEO4J")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Get comprehensive statistics
        result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            WITH count(e) AS entities
            MATCH (c:Community {group_id: $group_id})
            WITH entities, count(c) AS communities
            MATCH (r:RaptorNode {group_id: $group_id})
            WITH entities, communities, count(r) AS raptor_nodes
            MATCH (t:TextChunk {group_id: $group_id})
            WITH entities, communities, raptor_nodes, count(t) AS text_chunks
            MATCH (d:Document {group_id: $group_id})
            WITH entities, communities, raptor_nodes, text_chunks, count(d) AS documents
            OPTIONAL MATCH (:Entity {group_id: $group_id})-[rel]->(:Entity {group_id: $group_id})
            RETURN entities, communities, raptor_nodes, text_chunks, documents, count(rel) AS relationships
        """, group_id=GROUP_ID)
        
        record = result.single()
        if not record:
            print("   ❌ No data found - indexing may not have completed yet")
            driver.close()
            return False
        
        entities = record["entities"]
        relationships = record["relationships"]
        communities = record["communities"]
        documents = record["documents"]
        raptor_nodes = record["raptor_nodes"]
        text_chunks = record["text_chunks"]
        
        print(f"\n📊 Indexing Statistics:")
        print(f"   Documents: {documents}")
        print(f"   Text Chunks: {text_chunks}")
        print(f"   Entities: {entities}")
        print(f"   Relationships: {relationships}")
        print(f"   Communities: {communities}")
        print(f"   RAPTOR Nodes: {raptor_nodes}")
        
        # Check for duplicate Document nodes
        result = session.run("""
            MATCH (d:Document {group_id: $group_id})
            RETURN d.title AS title, count(*) AS count
            ORDER BY count DESC, title
        """, group_id=GROUP_ID)
        
        doc_counts = list(result)
        duplicates = [r for r in doc_counts if r["count"] > 1]
        
        if duplicates:
            print(f"\n⚠️  Duplicate Document nodes detected:")
            for r in duplicates:
                print(f"     {r['title']}: {r['count']} nodes")
        else:
            print(f"\n✅ No duplicate Document nodes (1 node per PDF)")
        
        # Compare with baseline
        print(f"\n📈 Comparison with Baseline (352 entities, 440 relationships):")
        if entities >= 300:
            print(f"   ✅ Entities: {entities} (target: 300+)")
        else:
            print(f"   ⚠️  Entities: {entities} (target: 300+, {((entities/352)-1)*100:+.1f}%)")
        
        if relationships >= 350:
            print(f"   ✅ Relationships: {relationships} (target: 350+)")
        else:
            print(f"   ⚠️  Relationships: {relationships} (target: 350+, {((relationships/440)-1)*100:+.1f}%)")
        
        if entities == 0:
            print("   ❌ No entities found - indexing may not have completed yet")
            driver.close()
            return False
        
        # Get all RAPTOR nodes with quality metrics
        result = session.run("""
            MATCH (n:RaptorNode)
            WHERE n.group_id = $group_id AND n.level > 0
            RETURN n.level as level,
                   n.cluster_coherence as coherence,
                   n.confidence_level as confidence_level,
                   n.confidence_score as confidence_score,
                   n.silhouette_score as silhouette_score,
                   n.child_count as child_count,
                   n.creation_model as model
            ORDER BY n.level
        """, group_id=GROUP_ID)
        
        nodes = list(result)
        
        if not nodes:
            print("\n   ℹ️  No RAPTOR nodes found with level > 0 (may still be processing)")
            driver.close()
            return entities > 0  # Pass if we have entities
        
        print(f"\n✅ Found {len(nodes)} RAPTOR nodes at level > 0")
        
        # Analyze quality metrics
        all_have_metrics = True
        for record in nodes:
            level = record["level"]
            coherence = record["coherence"]
            confidence = record["confidence_level"]
            conf_score = record["confidence_score"]
            child_count = record["child_count"]
            
            print(f"\nLevel {level}:")
            coherence_str = f"{coherence:.3f}" if coherence else "0.000"
            print(f"  Cluster Coherence: {coherence_str}")
            print(f"  Confidence Level: {confidence}")
            conf_score_str = f"{conf_score:.2f}" if conf_score else "0.00"
            print(f"  Confidence Score: {conf_score_str}")
            print(f"  Child Count: {child_count}")
            print(f"  Model: {record['model']}")
            
            # Verify metrics exist
            if coherence is None or coherence == 0.0:
                print(f"  ⚠️  No coherence calculated")
                all_have_metrics = False
            elif confidence == "unknown":
                print(f"  ⚠️  No confidence level assigned")
                all_have_metrics = False
            else:
                # Verify confidence matches coherence threshold
                if coherence >= 0.85 and confidence != "high":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'high' confidence, got '{confidence}'")
                    all_have_metrics = False
                elif 0.75 <= coherence < 0.85 and confidence != "medium":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'medium' confidence, got '{confidence}'")
                    all_have_metrics = False
                elif coherence < 0.75 and confidence != "low":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'low' confidence, got '{confidence}'")
                    all_have_metrics = False
                else:
                    print(f"  ✅ Phase 1 quality metrics correct!")
        
        driver.close()
        return all_have_metrics

if __name__ == "__main__":
    print(f"\nTesting GraphRAG Phase 1 with 5 documents")
    print(f"API: {API_URL}")
    print(f"Group ID: {GROUP_ID}\n")
    
    # Cleanup is destructive; disabled by default.
    if CLEANUP_ALL_GROUPS:
        cleanup_neo4j()
    else:
        print("=" * 80)
        print("CLEANUP: SKIPPED (set CLEANUP_ALL_GROUPS=true to enable)")
        print("=" * 80)
    
    # Index documents
    if not SKIP_INDEXING:
        if not test_indexing():
            print("\n❌ TEST FAILED: Indexing error")
            exit(1)
    else:
        print("\nℹ️  SKIP_INDEXING=true (will not call /index)")
    
    # If running the question bank, make sure pipeline steps needed by the
    # selected engines are complete before starting queries.
    engines_for_wait: list[str] = []
    if RUN_QUESTION_BANK:
        engines_for_wait = QA_ENGINES or ["vector", "local", "global", "drift", "raptor"]
    elif QA_ENGINES:
        engines_for_wait = QA_ENGINES

    require_communities = any(e in {"global", "drift"} for e in engines_for_wait)
    require_raptor = any(e == "raptor" for e in engines_for_wait)

    if not wait_for_indexing_completion(require_communities=require_communities, require_raptor=require_raptor):
        print("\n❌ TEST FAILED: Timed out waiting for indexing completion")
        exit(1)
    
    # Verify metrics (optional for endpoint-only engine correctness testing)
    if SKIP_NEO4J_VERIFY:
        print("\nℹ️  SKIP_NEO4J_VERIFY=true (will not query Neo4j directly)")
    else:
        if not verify_quality_metrics():
            print("\n⚠️  Warning: Some data may still be processing")
        else:
            print("\n✅ Data verified in Neo4j!")

    if RUN_LOCAL_QA:
        run_local_qa_smoke()

    # Question bank QA (10 per route + negatives per route)
    if RUN_QUESTION_BANK:
        bank = _load_question_bank(QUESTION_BANK_PATH)
        engines = QA_ENGINES or ["vector", "local", "global", "drift", "raptor"]
        for engine in engines:
            run_question_bank_engine(engine, bank)
    else:
        # Engine correctness QA (small per-endpoint smoke).
        if QA_ENGINES:
            for engine in QA_ENGINES:
                run_engine_qa_smoke(engine)
