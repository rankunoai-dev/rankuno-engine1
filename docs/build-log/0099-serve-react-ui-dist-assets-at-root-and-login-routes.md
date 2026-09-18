# Cycle 0099: Serve React UI static dist assets at root and login routes

- **Date**: 2026-09-18
- **Scope**: Serve compiled React UI assets (`rankuno-ui/dist`) from FastAPI server at `/`, `/login`, and `/assets`, falling back to `/api/v1/health` when assets are absent, and un-ignore `!rankuno-ui/dist` in Docker builds.
- **Commit**: uncommitted at time of writing
- **Quality gate**: **FULL QUALITY GATE PASSED** — ruff format, ruff check, mypy --strict, pytest (827 passed, 99% coverage), UI Component Tests (334 passed across 31 test files), drift check (176 markdown files clean).

---

## 1. Gate results

Full quality gate ran via `powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1`:

```
=== Step 1: ruff format --check ===
All files formatted correctly.

=== Step 2: ruff check ===
All checks passed!

=== Step 3: mypy --strict ===
Success: no issues found in 118 source files

=== Step 4: pytest with coverage ===
827 passed in 61.16s
TOTAL: 12,545 stmts, 75 missed, 99% coverage

=== Step 5: UI Component Tests ===
Test Files  31 passed (31)
     Tests  334 passed (334)
   Duration  29.35s

=== Full quality gate PASSED ===
```

`.\.venv\Scripts\python.exe scripts\drift_check.py`:

```
Running Architecture & Documentation Drift Audit...
PASSED: no drift detected across 176 markdown files.
```

---

## 2. What landed

- **`src/api/server.py`**: Added static asset mounting (`/assets` -> `rankuno-ui/dist/assets` using `fastapi.staticfiles.StaticFiles`) and single-page application entry point routes (`GET /` and `GET /login` returning `rankuno-ui/dist/index.html` via `FileResponse`). If `rankuno-ui/dist` is not present, `GET /` gracefully falls back to a redirect (`307`) to `${API_PREFIX}/health`.
- **`tests/api/test_server.py`**: Added `TestStaticUi` test suite covering index rendering at `/` and `/login`, static file delivery from `/assets`, and redirect fallback to `/api/v1/health` when assets are missing.
- **`.dockerignore`**: Modified ignore rules from `rankuno-ui` to `rankuno-ui/*` with `!rankuno-ui/dist` exception so pre-compiled frontend assets are included in production Docker containers while excluding `node_modules` and source code.
- **`rankuno-ui/src/components/gsc/GscAccountForm.tsx`**: Wrapped `form.validateFields()` in `submit()` with a `try/catch` block to handle antd form validation rejections gracefully and prevent unhandled promise rejections during modal interaction and unit testing.

---

## 3. Design decisions

- **Conditional asset mounting & fallback**: Mounting assets conditionally based on `rankuno-ui/dist.exists()` allows the API server to run cleanly both in production container deployments (where compiled frontend assets exist) and in bare API testing environments (where frontend assets are not pre-built) without raising startup file errors.
- **Explicit `/` and `/login` routes**: Routing both `/` and `/login` directly to `index.html` matches the React single-page application router entry points, resolving Railway cloud deployment 404 errors when navigating to the root application domain.

---

## 4. Bugs found and fixed

- **FastAPI 404 on Root Domain (`/`) on Railway Cloud Deployment**: Visiting the bare Railway app domain previously returned `{"detail":"Not Found"}` because FastAPI only had `/api/v1/*` routes registered. Mounting `/assets` and serving `index.html` on `/` and `/login` fixes root domain navigation.
- **Unhandled promise rejection in `GscAccountForm.tsx`**: `form.validateFields()` was previously invoked outside a `try/catch` block in `submit()`. When form validation failed on invalid input, `validateFields()` rejected with a field error object that threw an unhandled promise rejection in React Testing Library / Vitest tests. Wrapping `form.validateFields()` in a `try/catch` catches the validation failure cleanly.

---

## 5. Corrections

- Fixed broken relative link in `docs/build-log/0098-expires-at-is-not-deletion.md` referencing `adr/0016-cloud-api-authentication.md` to `../adr/0016-cloud-api-authentication.md`.

---

## 6. Explicitly not done

- **Client-side dynamic routing catch-all**: Deep nested non-API client routes (other than `/` and `/login`) rely on standard React SPA navigation; a wild-card fallback for arbitrary non-`/api` paths was deferred to avoid unintentionally shadowing API routes.

---

## 7. Files changed

- `src/api/server.py`
- `tests/api/test_server.py`
- `.dockerignore`
- `rankuno-ui/src/components/gsc/GscAccountForm.tsx`
- `docs/build-log/0098-expires-at-is-not-deletion.md`
- `docs/build-log/0099-serve-react-ui-dist-assets-at-root-and-login-routes.md`
- `docs/build-log/README.md`

---

## 8. Follow-ups

- Deploy committed changes to Railway and verify visiting `https://<app>.up.railway.app/` renders the React UI Login screen.
