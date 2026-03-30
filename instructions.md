# GradesView — Claude Code Build Instructions

## Project Overview

GradesView is a grade calculator app for students at Midland Public Schools (H.H. Dow High School) who use StudentVue/Synergy SIS. It lets students log in with their StudentVue credentials and see their grades in a better UI with a "what score do I need on the final" calculator.

The StudentVue SOAP API is dead (rejects all requests with UPD5304 version error). Instead, we reverse-engineered the PXP2 web portal login flow and scrape grade data by replaying browser requests. A working Python proof-of-concept already exists in `backend/scraper.py`.

The frontend was scaffolded with Lovable and lives in `frontend/`. It has UI components but NO backend integration yet — it needs to be wired up to the FastAPI backend.

---

## Architecture

```
User's Browser (React frontend)
        |
        | POST /api/login {username, password}
        | GET  /api/grades
        v
Your FastAPI Server (backend/)
        |
        | Replays browser session against StudentVue
        v
mi-mps.edupoint.com (Synergy/StudentVue PXP2 web portal)
```

- **Backend**: Python FastAPI server that acts as a proxy — logs into StudentVue on behalf of the user, scrapes grade data, returns clean JSON.
- **Frontend**: React app (scaffolded by Lovable) that shows grades and provides a grade calculator.

---

## File Structure

```
gradesview/
├── backend/
│   ├── main.py              ← FastAPI app entry point (TO BUILD)
│   ├── scraper.py           ← Working auth + scrape logic (EXISTS, needs refactoring)
│   ├── requirements.txt     ← Dependencies (TO BUILD)
│   └── grades_output.json   ← Sample API response for reference
├── frontend/
│   └── (Lovable React app — EXISTS, needs API integration)
├── docs/
│   ├── NOTES.md             ← Auth flow documentation
│   └── har-sample/          ← HAR file for reference if needed
└── README.md
```

---

## Step 1: Refactor backend/scraper.py into a clean module

The existing `scraper.py` is a working proof-of-concept that runs as a CLI script. Refactor it into a proper module with clean functions that `main.py` can import.

### The auth flow (5 steps):

**Step 1 — GET login page**
- URL: `GET https://mi-mps.edupoint.com/PXP2_Login_Student.aspx?regenerateSessionId=true`
- Extract three hidden form fields from the HTML response using regex:
  - `__VIEWSTATE` (value attribute of `<input id="__VIEWSTATE">`)
  - `__VIEWSTATEGENERATOR` (value attribute of `<input id="__VIEWSTATEGENERATOR">`)
  - `__EVENTVALIDATION` (value attribute of `<input id="__EVENTVALIDATION">`)
- These are ASP.NET anti-forgery tokens. They change on every page load. The server rejects the login POST without them.

**Step 2 — POST login credentials**
- URL: `POST https://mi-mps.edupoint.com/PXP2_Login_Student.aspx?regenerateSessionId=true`
- Content-Type: `application/x-www-form-urlencoded`
- Form fields:
  - `__VIEWSTATE`: (from step 1)
  - `__VIEWSTATEGENERATOR`: (from step 1)
  - `__EVENTVALIDATION`: (from step 1)
  - `ctl00$MainContent$username`: (user's StudentVue username, e.g. `chaichai28@midlandps.org`)
  - `ctl00$MainContent$password`: (user's password)
  - `ctl00$MainContent$Submit1`: `Login`
- On success: server responds with HTTP 302 redirect to `/Home_PXP2.aspx` and sets `ASP.NET_SessionId` cookie
- On failure: server returns 200 with the login page again (still on login URL)
- The `ASP.NET_SessionId` cookie is the auth token for all subsequent requests. Use `requests.Session()` to persist it automatically.

**Step 3 — Extract gradebook configuration**
- First, get the student's GUID:
  - URL: `POST https://mi-mps.edupoint.com/Service/RTCommunication.asmx/XMLDoRequest?PORTAL=StudentVUE`
  - Content-Type: `application/x-www-form-urlencoded`
  - Body: `xml=%3CREV_REQUEST%3E%3CEVENT+NAME%3D%22PXP_Get_StudentSummary%22%3E%3CREQUEST+WINDOW_ID%3D%22test%22%3E%3C%2FREQUEST%3E%3C%2FEVENT%3E%3C%2FREV_REQUEST%3E`
  - Response is XML containing JSON with `studentGU` field
- Then load the gradebook page:
  - URL: `GET https://mi-mps.edupoint.com/PXP2_Gradebook.aspx?AGU=0&studentGU={studentGU}`
  - The HTML response contains a JavaScript object `PXP.GBFocusData = {...};` embedded in a `<script>` tag
  - Extract this JSON with regex: `PXP\.GBFocusData\s*=\s*(\{.*?\});\s*\n` (with re.DOTALL)
  - This JSON contains:
    - `Schools[0].SchoolID` — the school ID (e.g. 9)
    - `Schools[0].SchoolName` — school name
    - `Schools[0].GradingPeriods[]` — array of grading periods, each with:
      - `Name` (e.g. "MP1", "MP2", "Sem1", "MP4")
      - `GU` — the grading period GUID
      - `OrgYearGU` — the org year GUID
      - `MarkPeriods[].GU` — the mark period GUID
      - `defaultFocus` — boolean, true for the current grading period
      - `GroupName` — "Regular" or "Semester Term"

**Step 4 — Get class list**
- URL: `POST https://mi-mps.edupoint.com/service/PXP2Communication.asmx/GradebookFocusClassInfo`
- Content-Type: `application/json; charset=utf-8`
- Extra header: `AGU: 0`
- JSON body:
  ```json
  {
    "request": {
      "gradingPeriodGU": "<from step 3, use the one where defaultFocus=true>",
      "AGU": "0",
      "orgYearGU": "<from step 3>",
      "schoolID": <from step 3, integer>,
      "markPeriodGU": "<from step 3, MarkPeriods[0].GU of the selected grading period>"
    }
  }
  ```
- Response JSON structure:
  ```json
  {
    "d": {
      "Data": {
        "Classes": [
          {"Name": "AP Calc BC H", "TeacherName": "Jason Watkins", "ID": 20456, ...},
          ...
        ]
      },
      "FOCUS_KEY": "16E4DCEF-329C-43B7-9CF2-5FCFD34832AF"
    }
  }
  ```
- The `FOCUS_KEY` is required for the next step. It's a session-scoped token tied to the current grading period view.

**Step 5 — Get grade data per class**
- URL: `POST https://mi-mps.edupoint.com/api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData`
- Content-Type: `application/json; charset=utf-8`
- **Required extra headers:**
  - `FOCUS_KEY: <from step 4>`
  - `CURRENT_WEB_PORTAL: StudentVUE`
  - `X-Requested-With: XMLHttpRequest`
- JSON body:
  ```json
  {
    "FriendlyName": "genericdata.classdata",
    "Method": "GetClassData",
    "Parameters": "{}"
  }
  ```
- Response contains full grade data for ONE class:
  ```json
  {
    "classId": 20254,
    "className": "(S2) Smallfield, J  AP Advanced Chemistry H ...",
    "GradingPeriodName": "MP4",
    "isAssignmentWeightingOn": true,
    "students": [{"name": "Raymond Chai", "calculatedMark": "A", "percentage": 100.0, ...}],
    "assignmentCategories": [...],
    "assignments": [{"name": "...", "score": "5", "points": "5", ...}],
    "reportCardScoreTypes": [...]
  }
  ```

**IMPORTANT — fetching ALL classes:**
The current scraper only fetches the default/first class. To get all 7 classes, you likely need to either:
1. Call GradebookFocusClassInfo for each class (may need a classID parameter), OR
2. Navigate to each class which changes the server-side focus, then call GetClassData

Investigate this by looking at the HAR file in `docs/har-sample/` — look for how the frontend switches between classes. The class switching likely happens through another endpoint or by re-calling GradebookFocusClassInfo with a different parameter. Check for any request that includes a classID or similar after the initial load.

Reference: `backend/grades_output.json` has a sample response from step 5 for one class.

---

## Step 2: Build backend/main.py (FastAPI)

Create a FastAPI app with these endpoints:

### `POST /api/login`
- Accepts: `{"username": "...", "password": "..."}`
- Runs steps 1-5 of the scraper
- Returns: full grade data for all classes, all grading periods info, student info
- Does NOT store credentials or session — stateless, each request is a fresh login cycle
- Should handle errors gracefully (bad credentials, StudentVue down, timeout, etc.)

### `GET /api/health`
- Simple health check endpoint, returns `{"status": "ok"}`

### CORS
- Enable CORS for the frontend origin (localhost:5173 for dev, plus whatever the production frontend URL will be)

### Error handling
- If login fails (still on login page after POST): return 401 with `{"error": "Invalid credentials"}`
- If StudentVue is down/timeout: return 502 with `{"error": "StudentVue is not responding"}`
- If grade data parsing fails: return 500 with `{"error": "Failed to parse grade data"}`

### Performance considerations (implement later, not now)
- Consider using `httpx` with async instead of `requests` for better performance
- Could parallelize the per-class grade fetches with `asyncio.gather()`
- Could add short-lived caching (e.g. 5 min) keyed by session to avoid re-login on refresh
- For MVP: just do it synchronously and sequentially, it's fine

### `backend/requirements.txt`
```
fastapi
uvicorn
requests
```

---

## Step 3: Integrate frontend with backend

The Lovable frontend in `frontend/` has UI components but no real data. Wire it up:

1. Create an API service layer (e.g. `frontend/src/services/api.ts` or similar) that calls the FastAPI backend
2. The login form should POST to `http://localhost:8000/api/login` (or whatever port)
3. On successful response, store the grade data in React state and render it
4. Show a loading spinner during the 3-6 second fetch (the backend makes ~12 requests to StudentVue sequentially)
5. Handle errors: show "Invalid credentials" on 401, "StudentVue is down" on 502, etc.

### Frontend environment
- The backend URL should be configurable via environment variable (e.g. `VITE_API_URL`)
- Default to `http://localhost:8000` for local dev

---

## Step 4: Grade calculator logic

The main feature beyond just showing grades is a "what do I need" calculator. The grade data from step 5 includes:
- `isAssignmentWeightingOn` — whether categories have weights
- `assignmentCategories` — array of categories with `weight` field
- `assignments` — every assignment with scores and points
- `reportCardScoreTypes` — the grading scale (A = 93-100, A- = 90-92.99, etc.)

The calculator should let a student:
1. See their current grade per class
2. Add a hypothetical assignment/exam score
3. See what their new grade would be
4. Ask "what do I need on the final to get an A?" and get the answer

This logic can be frontend-only — the backend just provides the raw data, the frontend does the math.

---

## Reference files

- `backend/scraper.py` — working proof-of-concept, the core logic to port
- `backend/grades_output.json` — sample grade data response (one class)
- `docs/NOTES.md` — condensed auth flow notes
- `docs/har-sample/*.har` — full HAR capture of a real browser session (contains every request/response, useful for debugging if an endpoint doesn't work as expected)

---

## How to run locally

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

Then open the frontend (probably http://localhost:5173), enter StudentVue credentials, and grades should load.~
