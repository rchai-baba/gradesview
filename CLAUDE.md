# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

GradesView is a grades viewer and calculator for Midland Public Schools students using StudentVue/Synergy SIS. The StudentVue SOAP API is dead (UPD5304 error), so the backend reverse-engineers the PXP2 web portal by replaying browser requests.

## How to run locally

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
bun install   # or npm install
bun run dev   # or npm run dev
```

Frontend runs at http://localhost:5173, backend at http://localhost:8000.

```bash
# Run frontend tests
cd frontend && bun run test
```

## Architecture

```
Browser (React) → FastAPI backend (backend/) → mi-mps.edupoint.com (StudentVue PXP2)
```

**Backend (`backend/`):**
- `main.py` — FastAPI app with three real endpoints: `POST /api/login`, `POST /api/class-detail`, `GET /api/health`. Plus debug endpoints.
- `scraper.py` — All StudentVue auth and scraping logic. Async functions using `httpx.AsyncClient`.

**Frontend (`frontend/src/`):**
- `pages/Index.tsx` — Login form. On success, saves data to `localStorage` and credentials to `sessionStorage`, then navigates to `/grades`.
- `pages/GradesHome.tsx` — Grade card grid with drag-to-reorder (dnd-kit). Sync button triggers a fresh `POST /api/login`.
- `pages/ClassDetail.tsx` — Per-class assignment view with grade calculator. Auto-fetches assignments via `POST /api/class-detail` if not yet loaded.
- `pages/Config.tsx` — Settings page (fetch mode, etc.).
- `services/api.ts` — All fetch logic and localStorage/sessionStorage helpers.
- `lib/grades.ts` — Grade computation (weighted/simple percent, what-if logic).
- `lib/semesterProjection.ts` — Semester grade projection across marking periods.
- `types.ts` — Shared TypeScript interfaces (`ApiResponse`, `ApiClass`, `ApiMarkingPeriod`, `ApiAssignment`).

## Key data flow

1. **Login** (`cards_only` mode by default): `POST /api/login` → returns class list with percentages but no assignment details. Fast (~3s).
2. **Sync button**: invalidates session cache and re-calls `/api/login` with whatever `fetch_mode` is configured.
3. **Class detail**: navigating to `/class/:classId` auto-triggers `POST /api/class-detail` if assignments aren't loaded. This patches the cached grades in localStorage via `patchClassMarkingPeriod`.
4. **Persistence**: all grade data lives in `localStorage` under `grades-data`. Credentials live in `sessionStorage` under `gradesview-session-creds` (cleared on tab close/logout).

## fetch_mode

The `fetch_mode` parameter controls how much data login fetches:
- `cards_only` — grade card data only (fast, no assignment lists)
- `current_period_only` — includes current period assignments
- `full` — all periods and assignments

Configured in localStorage via the Config page. Default is `cards_only`.

## StudentVue auth flow (5 steps)

Implemented in `backend/scraper.py`. Each step is async:
1. GET login page → extract `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`
2. POST credentials → get `ASP.NET_SessionId` cookie (302 redirect = success, 200 = bad creds)
3. POST RTCommunication → get `studentGU`; GET Gradebook page → extract `PXP.GBFocusData` JSON
4. POST `GradebookFocusClassInfo` → class list + `FOCUS_KEY`
5. POST `Transfer?action=genericdata.classdata-GetClassData` → grade data (requires `FOCUS_KEY`, `CURRENT_WEB_PORTAL: StudentVUE` headers)

## Important notes

- CORS is wide-open (`allow_origins=["*"]`) — fine for local/personal use.
- `_invalidate_session()` is called on every sync to force a fresh login (session caching is in the scraper).
- `mergedFromIds` on `ApiClass` — some classes span S1+S2 and are merged into one card; `synergyClassIdsFromClass()` in ClassDetail handles this.
- `assignmentsLoaded` flag prevents infinite refetch loops when a class genuinely has zero assignments.
- The `course_merge_config.json` in backend controls how Synergy class rows map to semester groups.
