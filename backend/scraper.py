"""
StudentVue Web Scraper — Midland Public Schools (mi-mps.edupoint.com)
Replicates the PXP2 web portal login flow and fetches gradebook data.

Auth flow:
  1. GET login page → extract __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
  2. POST login with credentials + ASP.NET tokens → get session cookie
  3. POST RTCommunication → get studentGU; GET gradebook page → extract GBFocusData
  4. POST GradebookFocusClassInfo → class list + FOCUS_KEY
  5. POST GetClassData (once per class, re-calling step 4 with classID to switch focus)
"""

import asyncio
import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

import httpx
import requests

BASE_URL = "https://mi-mps.edupoint.com"
LOGIN_URL = f"{BASE_URL}/PXP2_Login_Student.aspx?regenerateSessionId=true"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=utf-8",
    "X-Requested-With": "XMLHttpRequest",
}


class ScraperError(Exception):
    """Base class for scraper errors."""
    pass

class LoginError(ScraperError):
    """Invalid credentials or login page parsing failure."""
    pass

class StudentVueError(ScraperError):
    """StudentVue server unreachable or returned unexpected response."""
    pass

class ParseError(ScraperError):
    """Failed to parse grade data from response."""
    pass


# ---------------------------------------------------------------------------
# Async Session Pool — avoids focus conflicts by using multiple sessions
# ---------------------------------------------------------------------------

class AsyncSessionPool:
    def __init__(self, username, password, size=6):
        self.username = username
        self.password = password
        self.size = size
        self.clients = []
        self.available = asyncio.Queue()
        self.initialized = False

    async def initialize(self):
        if self.initialized:
            return
        # Create and login all sessions in parallel, but keep pool small to avoid server/proxy timeouts
        self.clients = [httpx.AsyncClient(timeout=30) for _ in range(self.size)]
        
        async def _login_staggered(client, i):
            await asyncio.sleep(i * 0.2)  # Very slight stagger
            await async_login(self.username, self.password, client)
            self.available.put_nowait(client)

        print(f"[Pool] Initializing {self.size} sessions...")
        tasks = [_login_staggered(c, i) for i, c in enumerate(self.clients)]
        await asyncio.gather(*tasks)
        self.initialized = True
        print(f"[Pool] All {self.size} sessions authenticated.")

    async def acquire(self) -> httpx.AsyncClient:
        return await self.available.get()

    async def release(self, client: httpx.AsyncClient):
        self.available.put_nowait(client)

    async def close(self):
        for client in self.clients:
            await client.aclose()


_SESSION_TTL = 1200  # seconds
_session_cache: dict[str, tuple[requests.Session, dict, float]] = {}
_session_lock = threading.Lock()


def _cache_key(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}:{password}".encode()).hexdigest()


def _get_or_create_session(username: str, password: str) -> tuple[requests.Session, dict]:
    """
    Return a cached (session, focus_data) if still fresh, otherwise login + get_gradebook_config.
    Saves ~4 serial HTTP round-trips on every call after the first.
    """
    key = _cache_key(username, password)
    now = time.monotonic()
    with _session_lock:
        entry = _session_cache.get(key)
        if entry:
            session, focus_data, ts = entry
            if now - ts < _SESSION_TTL:
                return session, focus_data
    session = login(username, password)
    focus_data = get_gradebook_config(session)
    with _session_lock:
        _session_cache[key] = (session, focus_data, now)
    return session, focus_data


def _invalidate_session(username: str, password: str) -> None:
    key = _cache_key(username, password)
    with _session_lock:
        _session_cache.pop(key, None)


def _get_session_with_retry(username: str, password: str) -> tuple[requests.Session, dict]:
    """Like _get_or_create_session but evicts and retries once on any error."""
    try:
        return _get_or_create_session(username, password)
    except (StudentVueError, ParseError):
        _invalidate_session(username, password)
        session = login(username, password)
        focus_data = get_gradebook_config(session)
        key = _cache_key(username, password)
        with _session_lock:
            _session_cache[key] = (session, focus_data, time.monotonic())
        return session, focus_data


async def async_login(username: str, password: str, client: httpx.AsyncClient) -> None:
    """
    Steps 1-2: GET login page for ASP.NET tokens, then POST credentials.
    Sets cookies on the provided httpx.AsyncClient.
    Raises LoginError on bad credentials, StudentVueError on network/server issues.
    """
    try:
        r = await client.get(LOGIN_URL, headers=BROWSER_HEADERS, timeout=15)
        r.raise_for_status()
    except httpx.TimeoutException:
        raise StudentVueError("Timed out connecting to StudentVue")
    except httpx.RequestError as e:
        raise StudentVueError(f"Could not reach StudentVue: {e}")

    # Use a more robust token extraction that handles attribute order and quoting variations
    def find_token(name, html):
        # Case 1: id="__TOKEN" ... value="VAL"
        m = re.search(f'id="{name}".*?value="([^"]*)"', html, re.DOTALL)
        if m: return m.group(1)
        # Case 2: name="__TOKEN" ... value="VAL"
        m = re.search(f'name="{name}".*?value="([^"]*)"', html, re.DOTALL)
        if m: return m.group(1)
        # Case 3: value="VAL" ... id/name="__TOKEN"
        m = re.search(f'value="([^"]*)".*?(id|name)="{name}"', html, re.DOTALL)
        if m: return m.group(1)
        return None

    vs_val = find_token("__VIEWSTATE", r.text)
    ev_val = find_token("__EVENTVALIDATION", r.text)
    vsg_val = find_token("__VIEWSTATEGENERATOR", r.text) or ""

    if vs_val is None or ev_val is None:
        print(f"  [Error] Failed to extract tokens. HTML sample: {r.text[:500]}")
        raise StudentVueError("Could not extract ASP.NET form tokens. The portal layout might have changed or access is blocked.")

    form_data = {
        "__VIEWSTATE": vs_val,
        "__VIEWSTATEGENERATOR": vsg_val,
        "__EVENTVALIDATION": ev_val,
        "ctl00$MainContent$username": username,
        "ctl00$MainContent$password": password,
        "ctl00$MainContent$Submit1": "Login",
    }

    print(f"  [Login] Sending credentials for {username}...")
    try:
        r = await client.post(
            LOGIN_URL,
            data=form_data,
            headers={**BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()
    except httpx.TimeoutException:
        print("  [Error] Login POST timed out")
        raise StudentVueError("Timed out during login POST")
    except httpx.RequestError as e:
        print(f"  [Error] Login POST failed: {e}")
        raise StudentVueError(f"Login POST failed: {e}")

    if "Home_PXP2.aspx" not in str(r.url) and "Home_PXP2" not in r.text:
        if "login" in str(r.url).lower():
            raise LoginError("Invalid credentials")
        # Ambiguous — treat as success if we have a session cookie
        if "ASP.NET_SessionId" not in client.cookies:
            raise LoginError("Login did not produce a session cookie")


async def async_get_gradebook_config(client: httpx.AsyncClient) -> dict:
    """
    Step 3: Get studentGU, then load gradebook page and extract GBFocusData.
    Returns the parsed GBFocusData dict.
    Raises StudentVueError or ParseError on failure.
    """
    # Get studentGU from student summary endpoint
    student_gu = "0"
    try:
        r = await client.post(
            f"{BASE_URL}/Service/RTCommunication.asmx/XMLDoRequest?PORTAL=StudentVUE",
            data="xml=%3CREV_REQUEST%3E%3CEVENT+NAME%3D%22PXP_Get_StudentSummary%22%3E%3CREQUEST+WINDOW_ID%3D%22test%22%3E%3C%2FREQUEST%3E%3C%2FEVENT%3E%3C%2FREV_REQUEST%3E",
            headers={
                **JSON_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
            },
            timeout=15,
        )
        if r.status_code == 200:
            gu_match = re.search(r'"studentGU":"([^"]+)"', r.text)
            if gu_match:
                student_gu = gu_match.group(1)
    except httpx.RequestError:
        pass  # Fall back to studentGU=0

    # Load gradebook page
    try:
        r = await client.get(
            f"{BASE_URL}/PXP2_Gradebook.aspx?AGU=0&studentGU={student_gu}",
            headers=BROWSER_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
    except httpx.TimeoutException:
        raise StudentVueError("Timed out loading gradebook page")
    except httpx.RequestError as e:
        raise StudentVueError(f"Failed to load gradebook page: {e}")

    # Extract GBFocusData JSON blob
    match = re.search(r'PXP\.GBFocusData\s*=\s*(\{.*?\});\s*\n', r.text, re.DOTALL)
    if not match:
        match = re.search(r'GBFocusData\s*=\s*(\{.+?\});\s', r.text, re.DOTALL)

    if not match:
        raise ParseError("Could not find GBFocusData in gradebook page")

    try:
        focus_data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse GBFocusData: {e}")

    # Also extract GBCurrentFocus to get the studentGU in the right format
    current_focus_match = re.search(r'PXP\.GBCurrentFocus\s*=\s*(\{.*?\});\s*\n', r.text, re.DOTALL)
    current_focus = {}
    if current_focus_match:
        try:
            current_focus = json.loads(current_focus_match.group(1))
        except json.JSONDecodeError:
            pass

    focus_data["_studentGU"] = student_gu
    focus_data["_currentFocusArgs"] = current_focus.get("FocusArgs", {})
    return focus_data


def _get_focus_info(focus_data: dict) -> dict:
    """
    Extract the default grading period and school info from GBFocusData.
    Returns a dict with keys: school, grading_period, mark_period_gu.
    """
    schools = focus_data.get("Schools", [])
    if not schools:
        raise ParseError("No schools found in GBFocusData")

    # Find first school with a valid SchoolID (try different casings)
    school = None
    for s in schools:
        s_id = s.get("SchoolID", s.get("SchoolId"))
        if s_id:
            s["SchoolID"] = s_id  # Normalize
            school = s
            break
    if not school:
        school = schools[0]
        school["SchoolID"] = school.get("SchoolID", school.get("SchoolId", ""))

    grading_periods = school.get("GradingPeriods", [])
    if not grading_periods:
        raise ParseError("No grading periods found for this school")

    # Find the default grading period, or fall back to last Regular one
    target_gp = next((gp for gp in grading_periods if gp.get("defaultFocus")), None)
    if not target_gp:
        regular_gps = [gp for gp in grading_periods if gp.get("GroupName") == "Regular"]
        target_gp = regular_gps[-1] if regular_gps else grading_periods[-1]

    # Normalize grading period identifiers
    target_gp["GU"] = target_gp.get("GU", target_gp.get("Gu", ""))
    target_gp["OrgYearGU"] = target_gp.get("OrgYearGU", target_gp.get("OrgYearGu", ""))

    mark_periods = target_gp.get("MarkPeriods", [])
    mark_period_gu = ""
    if mark_periods:
        mp = mark_periods[0]
        mark_period_gu = mp.get("GU", mp.get("Gu", ""))

    return {
        "school": school,
        "grading_period": target_gp,
        "mark_period_gu": mark_period_gu,
    }


def _class_focus_grade_hints(cls: dict) -> tuple[float | None, str | None]:
    """Best-effort grade from GradebookFocusClassInfo class row (no GetClassData)."""
    pct: float | None = None
    for key in ("Percent", "Percentage", "CurrentPercent", "GradePercent", "CurrentGradePercent"):
        v = cls.get(key)
        if v is not None and v != "":
            try:
                pct = float(v)
                break
            except (TypeError, ValueError):
                continue
    letter: str | None = None
    for key in ("CalculatedMark", "LetterGrade", "Grade", "CurrentGrade", "Mark"):
        v = cls.get(key)
        if isinstance(v, str) and v.strip():
            letter = v.strip()
            break
    return pct, letter


def _find_grading_period_by_name(focus_data: dict, period_name: str) -> dict | None:
    schools = focus_data.get("Schools", [])
    if not schools:
        return None
    for gp in schools[0].get("GradingPeriods", []):
        if gp.get("Name") == period_name:
            return gp
    return None


async def async_get_class_list(client: httpx.AsyncClient, focus_data: dict) -> dict:
    """
    Step 4: Get the list of classes for the current grading period.
    Returns {"classes": [...], "focus_key": "...", "focus_info": {...}}.
    """
    focus_info = _get_focus_info(focus_data)
    school = focus_info["school"]
    gp = focus_info["grading_period"]

    payload = {
        "request": {
            "gradingPeriodGU": gp.get("GU"),
            "AGU": "0",
            "orgYearGU": gp.get("OrgYearGU"),
            "schoolID": school.get("SchoolID"),
            "markPeriodGU": focus_info["mark_period_gu"],
        }
    }

    try:
        r = await client.post(
            f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
            content=json.dumps(payload),
            headers={
                **JSON_HEADERS,
                "AGU": "0",
                "Referer": f"{BASE_URL}/PXP2_Gradebook.aspx",
            },
            timeout=30,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 500:
            raise StudentVueError(f"Server error '500 Internal Server Error' for url '{e.request.url}'. This often means a session timeout or a malformed payload.")
        raise StudentVueError(f"Failed to fetch class list: {e}")
    except httpx.RequestError as e:
        raise StudentVueError(f"Failed to fetch class list: {e}")

    data = r.json()
    d = data.get("d", {})
    classes = d.get("Data", {}).get("Classes", [])
    focus_key = d.get("FOCUS_KEY", "")

    if not classes:
        raise ParseError("No classes returned from GradebookFocusClassInfo")

    return {
        "classes": classes,
        "focus_key": focus_key,
        "focus_info": focus_info,
    }


def _parse_current_grade_from_html(html: str) -> tuple[float | None, str | None]:
    """
    Parse the displayed current grade from LoadControl HTML.
    Looks for the <div id="current-grade"> block which contains:
      <div class="mark">A</div>
      <div class="score">97.87%</div>
    Returns (percentage, letter) or (None, None).
    """
    mark_m = re.search(r'id="current-grade".*?class="mark"[^>]*>\s*([^<\s][^<]*)', html, re.DOTALL)
    score_m = re.search(r'id="current-grade".*?class="score"[^>]*>\s*([\d.]+)%', html, re.DOTALL)
    letter = mark_m.group(1).strip() if mark_m else None
    pct: float | None = None
    if score_m:
        try:
            pct = float(score_m.group(1))
        except ValueError:
            pass
    return pct, letter


def _parse_titles_from_html(html: str) -> dict[int, str]:
    """
    Parse assignment titles from LoadControl HTML response.

    The HTML embeds a dxDataGrid config where each row object looks like:
      {"gradeBookId":"353452", ..., "GBAssignment":"{...\"value\":\"January MML\"...}", ...}

    GBAssignment is a doubly-encoded JSON string whose "value" key is the title.
    Returns {gradeBookId: title}.
    """
    titles: dict[int, str] = {}
    for gid_match in re.finditer(r'"gradeBookId":"(\d+)"', html):
        try:
            grade_book_id = int(gid_match.group(1))
        except ValueError:
            continue
        # Search for GBAssignment within the next 3000 chars (same row object)
        window = html[gid_match.start(): gid_match.start() + 3000]
        gb_match = re.search(r'"GBAssignment":"((?:[^"\\]|\\.)*)"', window)
        if not gb_match:
            continue
        try:
            # First decode: un-escape the outer JSON string escaping
            gb_str = json.loads('"' + gb_match.group(1) + '"')
            # Second decode: the value is itself a JSON object
            inner = json.loads(gb_str)
            title = inner.get("value", "").strip()
            if title:
                titles[grade_book_id] = title
        except (json.JSONDecodeError, ValueError):
            continue
    return titles


async def async_load_class_control_raw_html(
    client: httpx.AsyncClient,
    focus_info: dict,
    cls: dict,
    student_gu: str,
    focus_key: str,
) -> str:
    """Like _load_class_control but returns raw HTML string for debugging."""
    school = focus_info["school"]
    gp = focus_info["grading_period"]

    payload = {
        "request": {
            "control": "Gradebook_ClassDetails",
            "parameters": {
                "viewName": None,
                "studentGU": student_gu,
                "schoolID": school.get("SchoolID"),
                "classID": cls["ID"],
                "markPeriodGU": focus_info["mark_period_gu"],
                "gradePeriodGU": gp.get("GU"),
                "subjectID": -1,
                "teacherID": -1,
                "assignmentID": -1,
                "standardIdentifier": None,
                "AGU": "0",
                "OrgYearGU": gp.get("OrgYearGU"),
                "gradingPeriodGroup": None,
            },
        }
    }

    r = await client.post(
        f"{BASE_URL}/service/PXP2Communication.asmx/LoadControl",
        content=json.dumps(payload),
        headers={
            **JSON_HEADERS,
            "AGU": "0",
            "FOCUS_KEY": focus_key,
            "Referer": f"{BASE_URL}/PXP2_Gradebook.aspx",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("d", {}).get("Data", {}).get("html", "")


async def async_load_class_control(
    client: httpx.AsyncClient,
    focus_info: dict,
    cls: dict,
    student_gu: str,
    focus_key: str,
) -> dict[int, str]:
    """
    Replicates the browser's GB.LoadControl click handler — POSTs to LoadControl
    with the full FocusArgs (including classID) to set the server-side focus.
    Returns {gradeBookId: title} map.
    """
    try:
        html = await async_load_class_control_raw_html(client, focus_info, cls, student_gu, focus_key)
        return _parse_titles_from_html(html)
    except Exception:
        return {}


async def async_get_class_grades(client: httpx.AsyncClient, focus_key: str) -> dict:
    """
    Step 5: Fetch grade data for the currently server-focused class.
    Call _load_class_control first to switch focus to the desired class.
    """
    headers = {
        **JSON_HEADERS,
        "CURRENT_WEB_PORTAL": "StudentVUE",
        "FOCUS_KEY": focus_key,
    }
    payload = {
        "FriendlyName": "genericdata.classdata",
        "Method": "GetClassData",
        "Parameters": "{}",
    }

    try:
        r = await client.post(
            f"{BASE_URL}/api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData",
            content=json.dumps(payload),
            headers={
                **headers,
                "Referer": f"{BASE_URL}/PXP2_Gradebook.aspx",
            },
            timeout=30,
        )
        r.raise_for_status()
    except httpx.TimeoutException:
        raise StudentVueError("Timed out fetching class grades")
    except httpx.RequestError as e:
        raise StudentVueError(f"Failed to fetch class grades: {e}")

    return r.json()


def _transform_assignment(a: dict, title_map: dict[int, str] | None = None) -> dict:
    """Transform a raw StudentVue assignment into the frontend Assignment shape."""
    score_str = a.get("score", "")
    points_possible = float(a.get("pointsPossible", 0) or 0)
    excused = a.get("excused", False)

    # Convert score to float (numeric scores only; skip letter/non-numeric)
    try:
        points_earned = float(score_str)
    except (ValueError, TypeError):
        # Non-numeric score (e.g. letter grade, "I", "C", "N/A", or empty)
        points_earned = 0.0
        # If score is not a number, and isn't a known grade code that should count, excuse it.
        # StudentVue handles "N/A", "Not Graded", etc. as non-grading statuses.
        # Empty scores or "*" (placeholder) also shouldn't count as 0/Possible.
        s = str(score_str).strip().upper()
        if not s or s in ("N/A", "NOT GRADED", "NOT APPLICABLE", "*", "NE", "NOT ENTERED"):
            excused = True

    # Extra credit: x/0 — points go to earned only (no denominator)
    is_extra_credit = points_possible <= 0 and points_earned > 0

    # Build a readable title: prefer HTML-parsed title (by gradeBookId), then JSON fields, then category
    grade_book_id = a.get("gradeBookId")
    title = (
        (title_map.get(grade_book_id) if title_map and grade_book_id else None)
        or a.get("Measure")
        or a.get("assignmentName")
        or a.get("assignmentTitle")
        or a.get("category")
        or a.get("unit")
        or "Assignment"
    )
    category = a.get("category") or a.get("unit") or "Assignment"
    due_date = a.get("dueDate", "")

    return {
        "id": str(a.get("resultID", "")),
        "title": title,
        "pointsEarned": points_earned,
        "pointsTotal": points_possible,
        "category": category,
        "dueDate": due_date,
        "excused": excused,
        "isForGrading": a.get("isForGrading", True),
        "isExtraCredit": is_extra_credit,
        "debugFields": a,
    }


def _transform_class(raw: dict) -> dict:
    """Transform a raw GetClassData response into the frontend ClassData shape."""
    students = raw.get("students", [])
    student = students[0] if students else {}

    title_map = raw.get("_titleMap")
    assignments = [
        _transform_assignment(a, title_map)
        for a in raw.get("assignments", [])
        if a.get("isForGrading", True) and not a.get("hideInPortal", False)
    ]

    return {
        "id": str(raw.get("classId", "")),
        "name": _clean_class_name(raw.get("className", "")),
        "gradingType": "cumulative",
        "percentage": student.get("percentage"),
        "calculatedMark": student.get("calculatedMark"),
        "gradingPeriod": raw.get("GradingPeriodName"),
        "isAssignmentWeightingOn": raw.get("isAssignmentWeightingOn", False),
        "assignments": assignments,
    }


def _transform_categories(raw: dict) -> list[dict]:
    """Normalize assignmentCategories for the frontend (weighted grade calculator)."""
    out = []
    for c in raw.get("assignmentCategories") or []:
        try:
            w = float(c.get("weight", 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        out.append({
            "name": c.get("name") or "Category",
            "weight": w,
        })
    return out


def _load_course_merge_config() -> dict:
    """
    course_merge_config.json next to this file:
      mergeNameGroups: [["Title A", "Title B"], ...] — same teacher + any listed title → one card
      semesterGroups: [["MP1","MP2"], ["MP3","MP4"]] — period labels for semester projections
    """
    path = Path(__file__).resolve().with_name("course_merge_config.json")
    default_merge = [["Government", "Economics"], ["AP Government", "AP Economics"]]
    default_sem = [["MP1", "MP2"], ["MP3", "MP4"]]
    if not path.is_file():
        return {
            "mergeNameGroups": tuple(frozenset(x.lower() for x in g) for g in default_merge),
            "semesterGroups": default_sem,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups: list[frozenset[str]] = []
        for g in data.get("mergeNameGroups", []):
            if isinstance(g, list) and len(g) >= 2:
                groups.append(frozenset(str(x).strip().lower() for x in g if str(x).strip()))
        sg = data.get("semesterGroups")
        if not isinstance(sg, list) or not sg:
            sg = default_sem
        else:
            sg = [[str(x).strip() for x in row] for row in sg if isinstance(row, list) and row]
            if not sg:
                sg = default_sem
        return {
            "mergeNameGroups": tuple(groups),
            "semesterGroups": sg,
        }
    except (json.JSONDecodeError, OSError):
        return {
            "mergeNameGroups": tuple(frozenset(x.lower() for x in g) for g in default_merge),
            "semesterGroups": default_sem,
        }


def _merge_name_fingerprint(cleaned_name: str, merge_groups: tuple[frozenset[str], ...]) -> str:
    """Map alias titles to one stable string so S1 Gov + S2 Econ share a merge bucket."""
    n = cleaned_name.strip().lower()
    if not n:
        return ""
    for group in merge_groups:
        if n in group:
            return "merge:" + "|".join(sorted(group))
    return cleaned_name.strip()


def _combined_display_name(cids: list[int], class_meta: dict[int, dict]) -> str:
    """When a merged card spans different Synergy titles, show both (sorted)."""
    names: list[str] = []
    seen: set[str] = set()
    for cid in sorted(cids):
        raw = class_meta.get(cid, {}).get("Name", "")
        cname = _clean_class_name(raw)
        key = cname.strip().lower()
        if key and key not in seen:
            seen.add(key)
            names.append(cname.strip())
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return " / ".join(sorted(names, key=str.lower))


def _detect_cumulative(period_ids: dict[str, set[str]]) -> bool:
    """
    If the same assignment resultID appears in more than one marking period,
    the course is cumulative (carry-over) for the year.
    """
    id_periods: dict[str, list[str]] = {}
    for pname, ids in period_ids.items():
        for rid in ids:
            if not rid:
                continue
            id_periods.setdefault(rid, []).append(pname)
    return any(len(v) > 1 for v in id_periods.values())


def _canonical_class_key(meta: dict, merge_groups: tuple[frozenset[str], ...]) -> str:
    """
    Stable identity for merging S1/S2 Synergy rows that are the same enrollment
    (different class IDs, same course + teacher after cleaning).
    Different semester titles merge when listed in course_merge_config.json mergeNameGroups.
    """
    name = _clean_class_name(meta.get("Name", ""))
    fp = _merge_name_fingerprint(name, merge_groups)
    teacher = (meta.get("TeacherName") or "").strip().lower()
    return f"{fp}|{teacher}"


def _merge_semester_split_rows(
    class_period_data: dict[int, dict[str, dict | None]],
    class_meta: dict[int, dict],
    period_names: list[str],
    merge_groups: tuple[frozenset[str], ...],
) -> tuple[dict[str, dict[str, dict | None]], dict[str, dict], dict[str, list[int]]]:
    """
    Group rows by canonical key; merge each period column from whichever Synergy
    class ID has data (S1 IDs carry MP1–2, S2 IDs carry MP3–4, etc.).
    """
    buckets: dict[str, list[int]] = defaultdict(list)
    for cid, meta in class_meta.items():
        buckets[_canonical_class_key(meta, merge_groups)].append(cid)

    merged_period: dict[str, dict[str, dict | None]] = {}
    merged_meta: dict[str, dict] = {}
    merged_sources: dict[str, list[int]] = {}

    for ck, cids in buckets.items():
        cids = sorted(cids)
        periods_merged: dict[str, dict | None] = {}
        for pname in period_names:
            raw: dict | None = None
            for cid in cids:
                cell = class_period_data.get(cid, {}).get(pname)
                if cell:
                    raw = cell
                    break
            periods_merged[pname] = raw

        if len(cids) == 1:
            public_id = str(cids[0])
        else:
            public_id = hashlib.sha256(ck.encode()).hexdigest()[:16]

        merged_period[public_id] = periods_merged
        merged_sources[public_id] = cids
        best_cid = max(
            cids,
            key=lambda i: sum(1 for p in period_names if class_period_data.get(i, {}).get(p)),
        )
        merged_meta[public_id] = class_meta[best_cid]

    return merged_period, merged_meta, merged_sources


def _clean_class_name(raw_name: str) -> str:
    """
    Strip the teacher prefix from class names like:
    '(S2) Smallfield, J  AP Advanced Chemistry H (1 hr)(3) SEC:SC5422-1'
    → 'AP Advanced Chemistry H'
    """
    # Remove leading (S1)/(S2) etc.
    name = re.sub(r'^\(S\d+\)\s*', '', raw_name)
    # Remove 'LastName, F  ' teacher prefix
    name = re.sub(r'^[A-Za-z]+,\s+[A-Z]\s+', '', name)
    # Remove trailing section/hour info like ' (1 hr)(3) SEC:...'
    name = re.sub(r'\s*\(\d+ hr\).*$', '', name)
    name = re.sub(r'\s*SEC:.*$', '', name)
    return name.strip()


def _fetch_one_class_worker(
    username: str,
    password: str,
    grading_period_name: str,
    cls_id: int,
    focus_data_ro: dict,
) -> tuple[int, dict | None]:
    """
    Worker: logs in with its own session so each class gets independent server-side focus state.
    Returns (cls_id, raw_grade_data | None).
    focus_data_ro is the already-parsed GBFocusData from the main session (read-only: GU strings only).
    """
    try:
        session = login(username, password)
        school = focus_data_ro["Schools"][0]
        gp = _find_grading_period_by_name(focus_data_ro, grading_period_name)
        if not gp:
            return cls_id, None
        student_gu = focus_data_ro.get("_studentGU", "0")
        mark_periods = gp.get("MarkPeriods", [])
        mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""
        focus_info = {"school": school, "grading_period": gp, "mark_period_gu": mark_period_gu}

        # Get FOCUS_KEY for this independent session
        r = session.post(
            f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
            json={"request": {
                "gradingPeriodGU": gp.get("GU"),
                "AGU": "0",
                "orgYearGU": gp.get("OrgYearGU"),
                "schoolID": school.get("SchoolID"),
                "markPeriodGU": mark_period_gu,
            }},
            headers={**JSON_HEADERS, "AGU": "0"},
            timeout=15,
        )
        r.raise_for_status()
        d = r.json().get("d", {})
        focus_key = d.get("FOCUS_KEY", "")
        classes = d.get("Data", {}).get("Classes", [])
        cls_obj = next((c for c in classes if c["ID"] == cls_id), None)
        if not cls_obj:
            return cls_id, None

        title_map = _load_class_control(session, focus_info, cls_obj, student_gu, focus_key)
        raw = get_class_grades(session, focus_key)
        raw["_titleMap"] = title_map
        return cls_id, raw
    except Exception:
        return cls_id, None


async def async_scrape_cards_only(username: str, password: str) -> dict:
    """Fast path: one GradebookFocusClassInfo (default period) — no GetClassData per class."""
    async with httpx.AsyncClient(timeout=30) as client:
        await async_login(username, password, client)
        focus_data = await async_get_gradebook_config(client)
        student_gu = focus_data.get("_studentGU", "0")
        schools = focus_data.get("Schools", [])
        if not schools:
            raise ParseError("No schools in GBFocusData")

        school = schools[0]
        all_periods = school.get("GradingPeriods", [])
        regular_periods = [gp for gp in all_periods if gp.get("GroupName") == "Regular"]
        if not regular_periods:
            regular_periods = all_periods
        period_names = [gp["Name"] for gp in regular_periods]

        cfg = _load_course_merge_config()
        merge_groups: tuple[frozenset[str], ...] = cfg["mergeNameGroups"]
        semester_groups: list[list[str]] = cfg["semesterGroups"]

        cls_list = await async_get_class_list(client, focus_data)
        classes = cls_list["classes"]
        focus_key = cls_list["focus_key"]
        focus_info = cls_list["focus_info"]
        default_focus = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
        default_name = default_focus["Name"]

        class_period_data: dict[int, dict[str, dict]] = {}
        class_meta: dict[int, dict] = {}

        async def _fetch_card(cls: dict) -> tuple[int, float | None, str | None]:
            try:
                html = await async_load_class_control_raw_html(client, focus_info, cls, student_gu, focus_key)
                pct, letter = _parse_current_grade_from_html(html)
                if pct is None and letter is None:
                    pct, letter = _class_focus_grade_hints(cls)
                return cls["ID"], pct, letter
            except Exception:
                pct, letter = _class_focus_grade_hints(cls)
                return cls["ID"], pct, letter

        # Cards only can use ONE session because it only calls LoadControl (no focus conflict)
        card_tasks = [_fetch_card(cls) for cls in classes]
        card_results_list = await asyncio.gather(*card_tasks)
        card_results = {cid: (pct, letter) for cid, pct, letter in card_results_list}

        for cls in classes:
            cid = cls["ID"]
            class_meta[cid] = cls
            pct, letter = card_results.get(cid, (None, None))
            fake_raw = {
                "students": [{"percentage": pct, "calculatedMark": letter}],
                "assignments": [],
                "isAssignmentWeightingOn": False,
                "assignmentCategories": [],
                "GradingPeriodName": default_name,
            }
            if cid not in class_period_data:
                class_period_data[cid] = {}
            class_period_data[cid][default_name] = fake_raw

        merged_period_data, merged_class_meta, merged_sources = _merge_semester_split_rows(
            class_period_data, class_meta, [default_name], merge_groups,
        )

        all_class_data = []
        for public_id, periods in merged_period_data.items():
            meta = merged_class_meta.get(public_id, {})
            marking_periods = []
            period_id_sets: dict[str, set[str]] = {}
            for pname in period_names:
                raw = periods.get(pname) if pname == default_name else None
                if raw:
                    assignments = [
                        _transform_assignment(a, raw.get("_titleMap"))
                        for a in raw.get("assignments", [])
                        if a.get("isForGrading", True) and not a.get("hideInPortal", False)
                    ]
                    id_set = {a["id"] for a in assignments if a["id"]}
                    period_id_sets[pname] = id_set
                    students = raw.get("students", [])
                    student_data = students[0] if students else {}
                    marking_periods.append({
                        "label": pname,
                        "percentage": student_data.get("percentage"),
                        "calculatedMark": student_data.get("calculatedMark"),
                        "assignments": assignments,
                        "isAssignmentWeightingOn": raw.get("isAssignmentWeightingOn", False),
                        "assignmentCategories": _transform_categories(raw),
                    })
                else:
                    marking_periods.append({
                        "label": pname,
                        "percentage": None,
                        "calculatedMark": None,
                        "assignments": [],
                        "isAssignmentWeightingOn": False,
                        "assignmentCategories": [],
                    })

            grading_type = "cumulative" if _detect_cumulative(period_id_sets) else "noncumulative"
            current_mp_marking = next(
                (mp for mp in marking_periods if mp["label"] == default_name),
                marking_periods[-1] if marking_periods else {},
            )
            current_mp = periods.get(default_name)
            current_students = (current_mp or {}).get("students", [])
            current_student = current_students[0] if current_students else {}

            src_cids = merged_sources.get(public_id, [])
            if not src_cids and public_id.isdigit():
                src_cids = [int(public_id)]
            combined = _combined_display_name(src_cids, class_meta)
            display_name = combined if combined else _clean_class_name(meta.get("Name", ""))

            row = {
                "id": public_id,
                "name": display_name,
                "teacherName": meta.get("TeacherName", ""),
                "gradingType": grading_type,
                "percentage": current_student.get("percentage"),
                "calculatedMark": current_student.get("calculatedMark"),
                "currentPeriod": default_name,
                "markingPeriods": marking_periods,
                "isAssignmentWeightingOn": current_mp_marking.get("isAssignmentWeightingOn", False),
                "assignmentCategories": current_mp_marking.get("assignmentCategories", []),
                "assignments": [],
                "assignmentsLoaded": False,
            }
            src = merged_sources.get(public_id, [])
            if len(src) > 1:
                row["mergedFromIds"] = [str(x) for x in src]
            all_class_data.append(row)

        all_class_data.sort(key=lambda c: (c.get("name") or "").lower())

        return {
            "student": {"name": None},
            "periods": period_names,
            "classes": all_class_data,
            "semesterGroups": semester_groups,
            "fetchMode": "cards_only",
        }


async def async_scrape_class_detail(
    username: str,
    password: str,
    marking_period: str,
    synergy_class_ids: list[int],
) -> dict:
    """One class + one marking period async."""
    async with httpx.AsyncClient(timeout=30) as client:
        await async_login(username, password, client)
        focus_data = await async_get_gradebook_config(client)
        student_gu = focus_data.get("_studentGU", "0")
        schools = focus_data.get("Schools", [])
        if not schools:
            raise ParseError("No schools in GBFocusData")
        school = schools[0]
        gp = _find_grading_period_by_name(focus_data, marking_period)
        if not gp:
            raise ParseError(f"Unknown marking period: {marking_period}")

        mark_periods = gp.get("MarkPeriods", [])
        mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""
        focus_info = {"school": school, "grading_period": gp, "mark_period_gu": mark_period_gu}

        payload = {
            "request": {
                "gradingPeriodGU": gp.get("GU"),
                "AGU": "0",
                "orgYearGU": gp.get("OrgYearGU"),
                "schoolID": school.get("SchoolID"),
                "markPeriodGU": mark_period_gu,
            }
        }
        r = await client.post(
            f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
            content=json.dumps(payload),
            headers={
                **JSON_HEADERS,
                "AGU": "0",
                "Referer": f"{BASE_URL}/PXP2_Gradebook.aspx",
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json().get("d", {})
        focus_key = d.get("FOCUS_KEY", "")
        classes = d.get("Data", {}).get("Classes", [])

        raw: dict | None = None
        used_cls: dict | None = None
        last_err = None
        for cid in synergy_class_ids:
            cls = next((c for c in classes if c["ID"] == cid), None)
            if not cls: continue
            try:
                title_map = await async_load_class_control(client, focus_info, cls, student_gu, focus_key)
                raw = await async_get_class_grades(client, focus_key)
                raw["_titleMap"] = title_map
                used_cls = cls
                break
            except Exception as e:
                last_err = e

        if raw is None:
            raise StudentVueError(f"Could not load class detail: {last_err}")

        meta_map = {str(m.get("assignmentID", m.get("AssignmentID", ""))): m for m in (raw.get("Assignments") or [])}
        assignments = []
        for a in raw.get("assignments", []):
            if not a.get("isForGrading", True) or a.get("hideInPortal", False): continue
            aid = str(a.get("assignmentID", a.get("AssignmentID", "")))
            if aid in meta_map: a = {**a, **meta_map[aid]}
            assignments.append(_transform_assignment(a, raw.get("_titleMap")))

        students = raw.get("students", [])
        student_data = students[0] if students else {}

        marking_period_payload = {
            "label": marking_period,
            "percentage": student_data.get("percentage"),
            "calculatedMark": student_data.get("calculatedMark"),
            "assignments": assignments,
            "isAssignmentWeightingOn": raw.get("isAssignmentWeightingOn", False),
            "assignmentCategories": _transform_categories(raw),
        }

        return {
            "markingPeriod": marking_period_payload,
            "synergyClassIdUsed": used_cls["ID"] if used_cls else synergy_class_ids[0],
            "fetchMode": "detail",
        }


async def scrape(username: str, password: str, *, fetch_mode: str = "full") -> dict:
    """The optimized async entry point."""
    if fetch_mode == "cards_only":
        return await async_scrape_cards_only(username, password)

    async with httpx.AsyncClient(timeout=30) as main_client:
        await async_login(username, password, main_client)
        focus_data = await async_get_gradebook_config(main_client)
        student_gu = focus_data.get("_studentGU", "0")
        schools = focus_data.get("Schools", [])
        if not schools: raise ParseError("No schools in GBFocusData")
        school = schools[0]
        all_periods = school.get("GradingPeriods", [])
        regular_periods = [gp for gp in all_periods if gp.get("GroupName") == "Regular"]
        if not regular_periods: regular_periods = all_periods

        if fetch_mode == "current_period_only":
            default_gp = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
            regular_periods = [default_gp]

        cfg = _load_course_merge_config()
        merge_groups = cfg["mergeNameGroups"]
        semester_groups = cfg["semesterGroups"]

        # 1. Get class maps for each period using the main client
        period_info = {}
        for gp in regular_periods:
            fake_school = {**school, "GradingPeriods": [gp]}
            fake_focus = {**focus_data, "Schools": [fake_school]}
            res = await async_get_class_list(main_client, fake_focus)
            period_info[gp["Name"]] = res

        # 2. Collect all work items: (period_name, class_obj, focus_info, focus_key)
        work_items = []
        for pname, info in period_info.items():
            for cls in info["classes"]:
                work_items.append((pname, cls, info["focus_info"], info["focus_key"]))

        # 3. Process work items using a session pool
        pool_size = min(len(work_items), 4)
        pool = AsyncSessionPool(username, password, size=pool_size)
        await pool.initialize()

        class_period_data = {}
        class_meta = {}
        student_name = None

        async def worker():
            nonlocal student_name
            while work_items:
                try:
                    pname, cls, focus_info, focus_key = work_items.pop()
                except IndexError:
                    break
                
                client = await pool.acquire()
                try:
                    title_map = await async_load_class_control(client, focus_info, cls, student_gu, focus_key)
                    raw = await async_get_class_grades(client, focus_key)
                    raw["_titleMap"] = title_map
                    
                    cid = cls["ID"]
                    if cid not in class_period_data: class_period_data[cid] = {}
                    class_period_data[cid][pname] = raw
                    class_meta[cid] = cls

                    if student_name is None and raw.get("students"):
                        student_name = raw["students"][0].get("name")
                except Exception:
                    pass
                finally:
                    await pool.release(client)

        await asyncio.gather(*(worker() for _ in range(pool_size)))
        await pool.close()

        period_names = [gp["Name"] for gp in regular_periods]
        merged_period_data, merged_class_meta, merged_sources = _merge_semester_split_rows(
            class_period_data, class_meta, period_names, merge_groups
        )

        all_class_data = []
        for public_id, periods in merged_period_data.items():
            meta = merged_class_meta.get(public_id, {})
            marking_periods = []
            period_id_sets = {}
            for pname in period_names:
                raw = periods.get(pname)
                if raw:
                    meta_map = {str(m.get("assignmentID", m.get("AssignmentID", ""))): m for m in (raw.get("Assignments") or [])}
                    assignments = []
                    for a in raw.get("assignments", []):
                        if not a.get("isForGrading", True) or a.get("hideInPortal", False): continue
                        aid = str(a.get("assignmentID", a.get("AssignmentID", "")))
                        if aid in meta_map: a = {**a, **meta_map[aid]}
                        assignments.append(_transform_assignment(a, raw.get("_titleMap")))
                    
                    period_id_sets[pname] = {a["id"] for a in assignments if a["id"]}
                    student_data = raw.get("students", [{}])[0]
                    marking_periods.append({
                        "label": pname, "percentage": student_data.get("percentage"), "calculatedMark": student_data.get("calculatedMark"),
                        "assignments": assignments, "isAssignmentWeightingOn": raw.get("isAssignmentWeightingOn", False),
                        "assignmentCategories": _transform_categories(raw), "assignmentsLoaded": True,
                    })
                else:
                    marking_periods.append({
                        "label": pname, "percentage": None, "calculatedMark": None, "assignments": [],
                        "isAssignmentWeightingOn": False, "assignmentCategories": [], "assignmentsLoaded": True,
                    })

            default_period = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
            current_mp_marking = next((mp for mp in marking_periods if mp["label"] == default_period["Name"]), marking_periods[-1])
            curr_student = (periods.get(default_period["Name"]) or {}).get("students", [{}])[0]

            src_cids = merged_sources.get(public_id, [])
            combined = _combined_display_name(src_cids, class_meta)
            
            all_class_data.append({
                "id": public_id, "name": combined or _clean_class_name(meta.get("Name", "")),
                "teacherName": meta.get("TeacherName", ""),
                "gradingType": "cumulative" if _detect_cumulative(period_id_sets) else "noncumulative",
                "percentage": curr_student.get("percentage"), "calculatedMark": curr_student.get("calculatedMark"),
                "currentPeriod": default_period["Name"], "markingPeriods": marking_periods,
                "isAssignmentWeightingOn": current_mp_marking.get("isAssignmentWeightingOn", False),
                "assignmentCategories": current_mp_marking.get("assignmentCategories", []),
                "assignments": current_mp_marking["assignments"], "assignmentsLoaded": True,
            })

        all_class_data.sort(key=lambda c: c["name"].lower())
        return {"student": {"name": student_name}, "periods": period_names, "classes": all_class_data, "semesterGroups": semester_groups, "fetchMode": fetch_mode}


async def async_scrape_all_details(
    username: str,
    password: str,
    items: list[dict],  # [{"markingPeriod": str, "synergyClassIds": [int], "classId": str}]
) -> list[dict]:
    """
    Fetch assignments for multiple class×period combos in parallel using one login + session pool.
    Returns list of {"classId": str, "markingPeriod": str, "markingPeriodData": {...}} per item.
    Items that fail are omitted from results.
    """
    if not items:
        return []

    async with httpx.AsyncClient(timeout=30) as main_client:
        await async_login(username, password, main_client)
        focus_data = await async_get_gradebook_config(main_client)
        student_gu = focus_data.get("_studentGU", "0")
        schools = focus_data.get("Schools", [])
        if not schools:
            raise ParseError("No schools in GBFocusData")
        school = schools[0]

        # Group items by marking period so we only call GradebookFocusClassInfo once per period
        from collections import defaultdict
        by_period: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            by_period[item["markingPeriod"]].append(item)

        # Build focus_info + class list per period
        period_context: dict[str, dict] = {}
        for pname in by_period:
            gp = _find_grading_period_by_name(focus_data, pname)
            if not gp:
                continue
            mark_periods = gp.get("MarkPeriods", [])
            mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""
            focus_info = {"school": school, "grading_period": gp, "mark_period_gu": mark_period_gu}
            payload = {
                "request": {
                    "gradingPeriodGU": gp.get("GU"),
                    "AGU": "0",
                    "orgYearGU": gp.get("OrgYearGU"),
                    "schoolID": school.get("SchoolID"),
                    "markPeriodGU": mark_period_gu,
                }
            }
            r = await main_client.post(
                f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
                content=json.dumps(payload),
                headers={**JSON_HEADERS, "AGU": "0", "Referer": f"{BASE_URL}/PXP2_Gradebook.aspx"},
                timeout=30,
            )
            r.raise_for_status()
            d = r.json().get("d", {})
            period_context[pname] = {
                "focus_key": d.get("FOCUS_KEY", ""),
                "classes": d.get("Data", {}).get("Classes", []),
                "focus_info": focus_info,
            }

    # Build work items: (class_id_str, marking_period, synergy_ids, focus_key, focus_info, classes_list)
    work_items = []
    for pname, period_items in by_period.items():
        ctx = period_context.get(pname)
        if not ctx:
            continue
        for item in period_items:
            work_items.append({
                "classId": item["classId"],
                "markingPeriod": pname,
                "synergyClassIds": item["synergyClassIds"],
                "focus_key": ctx["focus_key"],
                "focus_info": ctx["focus_info"],
                "classes": ctx["classes"],
            })

    if not work_items:
        return []

    pool_size = min(len(work_items), 4)
    pool = AsyncSessionPool(username, password, size=pool_size)
    await pool.initialize()

    results = []
    results_lock = asyncio.Lock()

    async def worker():
        while work_items:
            try:
                item = work_items.pop()
            except IndexError:
                break
            client = await pool.acquire()
            try:
                raw = None
                for cid in item["synergyClassIds"]:
                    cls = next((c for c in item["classes"] if c["ID"] == cid), None)
                    if not cls:
                        continue
                    try:
                        title_map = await async_load_class_control(client, item["focus_info"], cls, student_gu, item["focus_key"])
                        raw = await async_get_class_grades(client, item["focus_key"])
                        raw["_titleMap"] = title_map
                        break
                    except Exception:
                        continue

                if raw is None:
                    continue

                assignments = []
                for a in raw.get("assignments", []):
                    if not a.get("isForGrading", True) or a.get("hideInPortal", False):
                        continue
                    assignments.append(_transform_assignment(a, raw.get("_titleMap")))

                student_data = (raw.get("students") or [{}])[0]
                mp_data = {
                    "label": item["markingPeriod"],
                    "percentage": student_data.get("percentage"),
                    "calculatedMark": student_data.get("calculatedMark"),
                    "assignments": assignments,
                    "isAssignmentWeightingOn": raw.get("isAssignmentWeightingOn", False),
                    "assignmentCategories": _transform_categories(raw),
                }
                async with results_lock:
                    results.append({
                        "classId": item["classId"],
                        "markingPeriod": item["markingPeriod"],
                        "markingPeriodData": mp_data,
                    })
            except Exception:
                pass
            finally:
                await pool.release(client)

    await asyncio.gather(*(worker() for _ in range(pool_size)))
    await pool.close()
    return results


def scrape_class_detail(username: str, password: str, marking_period: str, synergy_class_ids: list[int]) -> dict:
    """Sync wrapper for legacy calls (though we should update main.py)."""
    return asyncio.run(async_scrape_class_detail(username, password, marking_period, synergy_class_ids))


def scrape_sync(username: str, password: str, *, fetch_mode: str = "full") -> dict:
    """Sync wrapper for legacy calls."""
    return asyncio.run(scrape(username, password, fetch_mode=fetch_mode))
