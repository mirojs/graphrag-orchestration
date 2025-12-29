# Analyzer Reuse Frontend Fix - Handoff Summary (End of Day)

## 1. Context
Start Analysis was failing with Azure 404 (ModelNotFound) when backend reused an existing analyzer (deterministic ID). Root cause: frontend kept using the originally generated analyzer ID for POST :analyze instead of the backend-returned one.

## 2. Fix Implemented
- File: `code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeServices/proModeApiService.ts`
- Commit: `630031a1` on `main`
- Behavior: After PUT, extract `analyzerId` from response (`actualAnalyzerId`). If `reused: true` or ID differs, override local ID for POST.
- Response mapping updated to ensure returned `analyzerId` matches backend (reuse or newly created).

## 3. Current State
- Analyzer reuse working (backend returns `{ analyzerId, status: "ready", reused: true }`).
- Frontend logs reuse vs create path (`wasReused` check).
- Diagnostic `[DIAG]` console logging still enabled (instrumentation present).
- Deployment done with `APP_CONSOLE_LOG_ENABLED=true`.

## 4. Pending / Recommended Next Steps (Tomorrow)
| Priority | Action | Rationale |
|----------|--------|-----------|
| High | Run end-to-end Start Analysis twice with same schema | Confirm reuse path stability |
| High | Run Start Analysis with new schema | Confirm creation path still works |
| Medium | Remove verbose `[DIAG]` logs | Reduce noise / perf overhead |
| Medium | Toggle `APP_CONSOLE_LOG_ENABLED=false` for prod-like build | Silence logs for customer-facing environment |
| Optional | Add short doc note to existing Azure integration docs | Preserve tribal knowledge of reuse logic |
| Optional | Add Jest test (mock reuse response) | Guard against regression |

## 5. Verification Checklist
1. Prepare one schema with 2–3 fields.
2. Start Analysis (documents A,B) → expect normal creation path.
3. Start Analysis again (documents C) with SAME schema → expect `reused: true` in PUT response logs; POST should use deterministic ID.
4. Inspect network panel: POST URL must match analyzer ID from reuse response.
5. Confirm no Azure 404 errors.
6. Introduce a NEW schema → analyzer created (no `reused` flag) → POST uses new deterministic ID.

## 6. How to Test Quickly (Commands)
```bash
# Enable console logs (already enabled today)
cd ./code/content-processing-solution-accelerator/infra/scripts
APP_CONSOLE_LOG_ENABLED=true ./docker-build.sh

# Disable logs for production-like run
APP_CONSOLE_LOG_ENABLED=false ./docker-build.sh
```
Azure Container Apps (no redeploy):
```bash
az containerapp update --name <WEB_APP_NAME> --resource-group <RG> --set-env-vars APP_CONSOLE_LOG_ENABLED=true
az containerapp update --name <WEB_APP_NAME> --resource-group <RG> --set-env-vars APP_CONSOLE_LOG_ENABLED=false
```

## 7. Risk / Edge Cases
- If backend changes reuse response format (removes `analyzerId`), POST would fall back to original ID (could revive mismatch). Mitigation: add defensive null check/unit test.
- Quick Query path uses ephemeral IDs and intentionally skips reuse; unaffected.
- Removing logs: ensure not to delete functional code around `actualAnalyzerId` extraction.

## 8. Suggested Minimal Cleanup Diff (Tomorrow)
Remove only instrumentation:
- Console.log blocks with `[DIAG]` prefix in `proModeApiService.ts`.
- Keep warnings about ID mismatch.

## 9. Reference Commits
- Working historical fix: `c25d9aa6` (initial reuse handling introduction)
- Current enhancement: `630031a1` (ensures propagation + structured logging)

## 10. Quick Snippet (Core Logic)
```ts
const createData = validateApiResponse(createResponse, 'Create Content Analyzer', [200,201]);
const actualAnalyzerId = (createData as any).analyzerId || request.analyzerId;
const wasReused = (createData as any).reused === true;
// Use actualAnalyzerId for POST
const actualAnalyzeEndpoint = `/pro-mode/content-analyzers/${actualAnalyzerId}:analyze?api-version=2025-05-01-preview`;
```

## 11. Pickup Instructions
Start with verification checklist. If all green:
1. Remove `[DIAG]` logs.
2. Redeploy with logs disabled.
3. (Optional) Add regression test and doc note.

---
Prepared: 2025-11-22 End of Day
"Ready for pickup tomorrow."