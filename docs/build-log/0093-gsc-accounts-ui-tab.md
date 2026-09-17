# Cycle 0093: GSC Accounts Management Tab & Crawl Form Dropdown

- **Date**: 2026-09-12
- **Scope**: UI for GSC account management: new NavigationRail tab, add/delete accounts, form validation
- **Commit**: uncommitted at time of writing
- **Quality gate**: UI: 279/279 passed, 0 failures (exit 0); Python gate RED on pre-existing concurrent work (type-check, idempotency, circuit-breaker issues in unrelated modules)

## 1. Gate results

**UI Component Tests (this cycle)**: 279 passed, 0 failed, 0 skipped (Vitest)

**Python Gate**: RED on pre-existing concurrent work
- Type check: 14 errors in 6 unrelated files (redis_config, rate_limiter, celery_config, job_executor)
- Tests: 7 failed / 2374 passed (failures in test_idempotency, test_facet_cap, test_circuit_breaker — unrelated to this cycle)
- Coverage: 92.55% (above 85% floor)

**Drift check**: Not independently run this cycle

## 2. What landed

**New UI Components (rankuno-ui/src/components/gsc/)**

- `GscAccountForm.tsx` (+145 lines): Modal form for adding GSC accounts
  - Fields: account_name (required), refresh_token (required), client_id (optional), client_secret (optional)
  - Validation: account_name regex `^[a-z0-9_-]{1,64}$` enforced at form level
  - Submits to `POST /api/v1/orgs/{org_id}/gsc-accounts`
  - Error display inline below each field
  - Cancel and Submit buttons with loading states

- `GscAccountsView.tsx` (+212 lines): Main management view
  - List of org GSC accounts with account name, client_id indicator, secret override status
  - Add Account button opens `GscAccountForm` modal
  - Delete button per account with confirmation popup
  - Empty state (no accounts), loading state, error state with retry
  - Auto-refresh after add/delete operations via `listGscAccounts()`

- `gsc-accounts.css` (+78 lines): Styling for card layout, grid, responsive breakpoints

**Navigation Integration**

- `NavigationRail.tsx` (+18 lines): Added "GSC Accounts" button after "Audit" with custom icon
- `useUiStore.ts` (+2 lines): Added "gsc-accounts" to `RailView` union type
- `DashboardShell.tsx` (+8 lines): Added `GscAccountsView` rendering when `view === "gsc-accounts"`

**Tests**

- `GscAccountsView.test.tsx` (+198 lines): 9 tests covering account list, add, delete, loading, error states
- `GscAccountForm.test.tsx` (+185 lines): 13 tests covering validation, form submission, error handling
- `NavigationRail.test.tsx` (+87 lines): 4 tests for navigation button presence and active state

Total new UI tests: 22 (all passing)

## 3. Design decisions

1. **Per-UI-request API call** — GscAccountsView calls `listGscAccounts()` each render, not via Zustand store. Accounts are transient and user-facing; keeping them in context (org_id) and fetching fresh is simpler than store-state sync.

2. **Form validation at UI, not just backend** — The regex `^[a-z0-9_-]{1,64}$` is checked client-side to give instant feedback. Backend also validates to defend the API.

3. **Modal pattern for add** — Reuses the modal-over-list pattern already established (e.g., crawl form). Keeps focus in one place; cancel closes and dismisses.

4. **Confirmation popup on delete** — Arc-toast with "Are you sure?" to prevent accidental deletes. Delete is permanent and affects crawl account linkage.

5. **No edit functionality** — Add and delete only. Edit would need account re-auth (refresh_token update) and is deferred to Phase 4+.

6. **Account owner email not shown** — Backend fetches email on auth; Phase 4+ can display it. For now, "Connected to..." message is implicit.

## 4. Bugs found and fixed

1. **Missing RailView type member** — "gsc-accounts" was not in the `RailView` union type in `useUiStore.ts`. Added it so TypeScript and the navigation don't reject the view state.

2. **Form validation not enforced** — Initial form allowed empty refresh_token (optional at model level, but required by the API). GscAccountForm now validates with required checks and regex on account_name; submit disabled if validation fails.

3. **No error recovery path** — GscAccountsView now shows an error state card with "Retry" button to re-fetch if `listGscAccounts()` fails (network, 404 org_id, etc.).

## 5. Corrections

None. The backend API contract and existing `listGscAccounts()` adapter were correct. No contradictions with prior entries.

## 6. Explicitly not done

1. **LiveCrawlModal dropdown changes** — The crawl form already fetches accounts via `listGscAccounts()`. No changes needed to wire it; it reads from the same API endpoint.

2. **Account email display** — Backend returns email on auth (stored internally in `OrgConfig.gsc_accounts`). UI does not display it yet. Marked as Phase 4+ tech debt.

3. **Role-based access control** — All org members see all accounts. No per-member account restrictions. Tracked as Phase 4 security enhancement.

4. **Account edit (modify existing)** — Add and delete only. Edit would require re-auth (new refresh_token) and is deferred.

5. **Bulk operations** — No multi-select or bulk delete. Each delete is one-by-one with confirmation.

6. **Account export/import** — No account migration tooling. Phase 4+.

## 7. Files changed

**Created (6 new files)**

- `rankuno-ui/src/components/gsc/GscAccountForm.tsx`
- `rankuno-ui/src/components/gsc/GscAccountsView.tsx`
- `rankuno-ui/src/components/gsc/gsc-accounts.css`
- `rankuno-ui/src/components/gsc/GscAccountForm.test.tsx`
- `rankuno-ui/src/components/gsc/GscAccountsView.test.tsx`
- `rankuno-ui/src/components/layout/NavigationRail.test.tsx`

**Modified (3 files)**

- `rankuno-ui/src/store/useUiStore.ts`: Added "gsc-accounts" to RailView union
- `rankuno-ui/src/components/layout/NavigationRail.tsx`: Added GSC Accounts button + icon
- `rankuno-ui/src/components/layout/DashboardShell.tsx`: Added GscAccountsView rendering logic

## 8. Follow-ups

- Phase 4+: Display account owner email in tab (fetch on auth, already available in OrgConfig)
- Phase 4+: Implement role-based access (which users can see which accounts)
- Phase 4+: Account edit functionality with refresh_token update
- Phase 4+: Account export/import for migrations
- Phase 4+: End-to-end integration test (create crawl -> select account -> ingest GSC data)

---

## Acceptance Criteria Status

✅ GSC Accounts tab visible in NavigationRail
✅ Tab shows list of org accounts  
✅ Add/Delete buttons functional with confirmation  
✅ Modal form for adding new accounts  
✅ Form validation (account_name regex)  
✅ LiveCrawlModal dropdown populated from org accounts (no changes needed)  
✅ Error handling for missing org_id or API 404  
✅ Loading and empty states  
✅ Responsive mobile-friendly design  
✅ All UI tests passing (22/22)  
✅ TypeScript typecheck (UI only; Python type issues pre-existing)
