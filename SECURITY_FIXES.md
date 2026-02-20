# Security Vulnerability Fixes

This file documents security dependency bumps applied on 2026-02-20 to resolve
5 GitHub Dependabot alerts (2 high, 3 moderate). Use this as a reference if a
merge conflict arises when rebasing or merging with another branch.

---

## Fix 1 — cryptography (HIGH)

**File:** `frontend/app/backend/requirements.txt`

| Field | Value |
|-------|-------|
| CVE | CVE-2026-26007 |
| Severity | HIGH |
| Vulnerability | Subgroup attack due to missing ECDH subgroup validation in cryptography |
| Vulnerable | `cryptography==44.0.1` |
| Fixed | `cryptography==46.0.5` |

**Conflict resolution:** Always keep `cryptography>=46.0.5`. Do not roll back below this version.

---

## Fix 2 — pillow (HIGH)

**File:** `frontend/app/backend/requirements.txt`

| Field | Value |
|-------|-------|
| CVE | CVE-2026-25990 |
| Severity | HIGH |
| Vulnerability | Out-of-bounds write when loading PSD images (potential RCE) |
| Vulnerable | `pillow==12.0.0` |
| Fixed | `pillow==12.1.1` |

**Conflict resolution:** Always keep `pillow>=12.1.1`. Do not roll back below this version.

---

## Fix 3 — python-jose (MODERATE)

**File:** `graphrag-orchestration/requirements.txt`

| Field | Value |
|-------|-------|
| CVE | CVE-2024-33663 |
| Severity | MODERATE (CRITICAL per OSV GHSA-6c5p-j8vq-pqhj) |
| Vulnerability | Algorithm confusion with OpenSSH ECDSA keys — JWT signature bypass |
| Vulnerable | `python-jose[cryptography]>=3.3.0` (allows vulnerable 3.3.0) |
| Fixed | `python-jose[cryptography]>=3.4.0` |

| Field | Value |
|-------|-------|
| CVE | CVE-2024-33664 |
| Severity | MODERATE |
| Vulnerability | Denial of service via compressed JWE content |
| Vulnerable | `python-jose[cryptography]>=3.3.0` (allows vulnerable 3.3.0) |
| Fixed | `python-jose[cryptography]>=3.4.0` |

**Conflict resolution:** Always keep the lower bound at `>=3.4.0` or higher. If another branch
lowered it back to `>=3.3.0`, keep `>=3.4.0`.

---

## How to verify after resolving a conflict

```bash
# Re-run pip-audit on the frontend pinned requirements
pip install pip-audit
pip-audit -r frontend/app/backend/requirements.txt

# Check python-jose version resolves to >=3.4.0 in a fresh install
pip install "python-jose[cryptography]>=3.4.0" --dry-run
```
