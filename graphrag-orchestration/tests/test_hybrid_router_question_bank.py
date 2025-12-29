"""Question-bank-driven tests for the Hybrid 3-route router.

These tests are intentionally *routing-only* (no external services required).
They validate:
- Profile constraints (High Assurance disables Vector; Speed Critical disables DRIFT)
- A couple of sanity checks that Profile A can still pick Vector and DRIFT

The questions are sourced from the repo's markdown question bank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.hybrid.router.main import DeploymentProfile, HybridRouter, QueryRoute


QUESTION_BANK_CANDIDATES = [
    # Original location (older scripts assumed this)
    Path(__file__).resolve().parents[2] / "QUESTION_BANK_5PDFS_2025-12-24.md",
    # Current archived location (post-cleanup)
    Path(__file__).resolve().parents[2]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md",
]


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    text: str


_SECTION_RE = re.compile(r"^##\s+([A-Z])\)\s+(.+?)\s*$")
_Q_RE = re.compile(r"^\s*\d+\.\s+\*\*(Q-[A-Z]\d+):\*\*\s*(.+?)\s*$")


def _load_question_bank_text() -> str:
    for candidate in QUESTION_BANK_CANDIDATES:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(
        "Question bank not found. Tried: " + ", ".join(str(p) for p in QUESTION_BANK_CANDIDATES)
    )


def _parse_questions(md: str) -> dict[str, list[BankQuestion]]:
    """Return a dict keyed by section letter (A..E) with ordered questions."""
    sections: dict[str, list[BankQuestion]] = {}
    current_section: str | None = None

    for line in md.splitlines():
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            section_id = m_sec.group(1)
            current_section = section_id
            sections.setdefault(section_id, [])
            continue

        m_q = _Q_RE.match(line)
        if m_q and current_section:
            qid = (m_q.group(1) or "").strip()
            text = (m_q.group(2) or "").strip()
            sections[current_section].append(BankQuestion(qid=qid, text=text))

    return sections


@pytest.fixture(scope="session")
def question_bank() -> dict[str, list[BankQuestion]]:
    md = _load_question_bank_text()
    return _parse_questions(md)


def _pick_by_prefix(questions: list[BankQuestion], prefix: str) -> list[BankQuestion]:
    return [q for q in questions if q.qid.startswith(prefix)]


@pytest.mark.asyncio
async def test_question_bank_has_expected_sections(question_bank):
    # Ensures our parser works and the bank hasn't drifted.
    assert "A" in question_bank, "Missing section A (Vector)"
    assert "B" in question_bank, "Missing section B (Local)"
    assert "C" in question_bank, "Missing section C (Global)"
    assert "D" in question_bank, "Missing section D (Drift)"

    assert _pick_by_prefix(question_bank["A"], "Q-V"), "No Q-V questions found in section A"
    assert _pick_by_prefix(question_bank["B"], "Q-L"), "No Q-L questions found in section B"
    assert _pick_by_prefix(question_bank["C"], "Q-G"), "No Q-G questions found in section C"
    assert _pick_by_prefix(question_bank["D"], "Q-D"), "No Q-D questions found in section D"


@pytest.mark.asyncio
async def test_profile_b_disables_vector_route_for_vector_questions(question_bank):
    """High-assurance audit must never route to Vector RAG."""
    router = HybridRouter(profile=DeploymentProfile.HIGH_ASSURANCE_AUDIT, llm_client=None)

    vector_qs = _pick_by_prefix(question_bank["A"], "Q-V")
    assert vector_qs, "No vector questions found"

    # Test all Q-V items: even if base routing would pick VECTOR_RAG,
    # profile constraints must force LOCAL_GLOBAL.
    for q in vector_qs:
        route = await router.route(q.text)
        assert route != QueryRoute.VECTOR_RAG, f"Profile B routed {q.qid} to Vector"
        assert route == QueryRoute.LOCAL_GLOBAL, f"Profile B should fall through to Local/Global for {q.qid}"


@pytest.mark.asyncio
async def test_profile_c_disables_drift_route_for_drift_questions(question_bank):
    """Speed-critical must never route to DRIFT multi-hop."""
    router = HybridRouter(profile=DeploymentProfile.SPEED_CRITICAL, llm_client=None)

    drift_qs = _pick_by_prefix(question_bank["D"], "Q-D")
    assert drift_qs, "No drift questions found"

    for q in drift_qs:
        route = await router.route(q.text)
        assert route != QueryRoute.DRIFT_MULTI_HOP, f"Profile C routed {q.qid} to DRIFT"
        # Profile C only disables DRIFT. Depending on heuristics, a question may still
        # legitimately route to VECTOR_RAG or LOCAL_GLOBAL.


@pytest.mark.asyncio
async def test_profile_a_routes_simple_fact_to_vector(question_bank):
    """Sanity check: Profile A should still use Vector for obvious fact lookups."""
    router = HybridRouter(profile=DeploymentProfile.GENERAL_ENTERPRISE, llm_client=None)

    # Pick a couple of the simplest fact lookups.
    vector_qs = _pick_by_prefix(question_bank["A"], "Q-V")
    assert vector_qs, "No vector questions found"

    samples = [q for q in vector_qs if q.qid in {"Q-V1", "Q-V2", "Q-V3"}]
    if not samples:
        samples = vector_qs[:3]

    for q in samples:
        route = await router.route(q.text)
        assert route == QueryRoute.VECTOR_RAG, f"Expected Vector for {q.qid} under Profile A"


@pytest.mark.asyncio
async def test_profile_a_can_route_multi_hop_to_drift(question_bank):
    """Sanity check: Profile A can select DRIFT for clearly multi-hop queries."""
    router = HybridRouter(profile=DeploymentProfile.GENERAL_ENTERPRISE, llm_client=None)

    # Use a synthetic query with strong multi-hop + analytical signals to ensure
    # DRIFT remains reachable even when the question bank content evolves.
    query = (
        "Analyze our overall risk exposure through subsidiaries and trace the relationship between entities "
        "across all related parties in general."
    )
    route = await router.route(query)
    assert route == QueryRoute.DRIFT_MULTI_HOP, "Expected DRIFT for a clearly multi-hop analytical query"
