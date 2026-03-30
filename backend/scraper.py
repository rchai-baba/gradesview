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

import re
import json
import requests
from html import unescape

BASE_URL = "https://mi-mps.edupoint.com"
LOGIN_URL = f"{BASE_URL}/PXP2_Login_Student.aspx?regenerateSessionId=true"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
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


def login(username: str, password: str) -> requests.Session:
    """
    Steps 1-2: GET login page for ASP.NET tokens, then POST credentials.
    Returns an authenticated requests.Session.
    Raises LoginError on bad credentials, StudentVueError on network/server issues.
    """
    session = requests.Session()

    try:
        r = session.get(LOGIN_URL, headers=BROWSER_HEADERS, timeout=15)
        r.raise_for_status()
    except requests.Timeout:
        raise StudentVueError("Timed out connecting to StudentVue")
    except requests.RequestException as e:
        raise StudentVueError(f"Could not reach StudentVue: {e}")

    viewstate = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', r.text)
    viewstate_gen = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', r.text)
    event_validation = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', r.text)

    if not viewstate or not event_validation:
        raise StudentVueError("Could not extract ASP.NET form tokens from login page")

    form_data = {
        "__VIEWSTATE": viewstate.group(1),
        "__VIEWSTATEGENERATOR": viewstate_gen.group(1) if viewstate_gen else "",
        "__EVENTVALIDATION": event_validation.group(1),
        "ctl00$MainContent$username": username,
        "ctl00$MainContent$password": password,
        "ctl00$MainContent$Submit1": "Login",
    }

    try:
        r = session.post(
            LOGIN_URL,
            data=form_data,
            headers={**BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
            allow_redirects=True,
        )
        r.raise_for_status()
    except requests.Timeout:
        raise StudentVueError("Timed out during login POST")
    except requests.RequestException as e:
        raise StudentVueError(f"Login POST failed: {e}")

    if "Home_PXP2.aspx" not in r.url and "Home_PXP2" not in r.text:
        if "login" in r.url.lower():
            raise LoginError("Invalid credentials")
        # Ambiguous — treat as success if we have a session cookie
        if "ASP.NET_SessionId" not in session.cookies:
            raise LoginError("Login did not produce a session cookie")

    return session


def get_gradebook_config(session: requests.Session) -> dict:
    """
    Step 3: Get studentGU, then load gradebook page and extract GBFocusData.
    Returns the parsed GBFocusData dict.
    Raises StudentVueError or ParseError on failure.
    """
    # Get studentGU from student summary endpoint
    student_gu = "0"
    try:
        r = session.post(
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
    except requests.RequestException:
        pass  # Fall back to studentGU=0

    # Load gradebook page
    try:
        r = session.get(
            f"{BASE_URL}/PXP2_Gradebook.aspx?AGU=0&studentGU={student_gu}",
            headers=BROWSER_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
    except requests.Timeout:
        raise StudentVueError("Timed out loading gradebook page")
    except requests.RequestException as e:
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

    school = schools[0]
    grading_periods = school.get("GradingPeriods", [])

    # Find the default grading period, or fall back to last Regular one
    target_gp = next((gp for gp in grading_periods if gp.get("defaultFocus")), None)
    if not target_gp:
        regular_gps = [gp for gp in grading_periods if gp.get("GroupName") == "Regular"]
        target_gp = regular_gps[-1] if regular_gps else grading_periods[-1]

    mark_periods = target_gp.get("MarkPeriods", [])
    mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""

    return {
        "school": school,
        "grading_period": target_gp,
        "mark_period_gu": mark_period_gu,
    }


def get_class_list(session: requests.Session, focus_data: dict) -> dict:
    """
    Step 4: Get the list of classes for the current grading period.
    Returns {"classes": [...], "focus_key": "...", "focus_info": {...}}.
    """
    focus_info = _get_focus_info(focus_data)
    school = focus_info["school"]
    gp = focus_info["grading_period"]

    payload = {
        "request": {
            "gradingPeriodGU": gp["GU"],
            "AGU": "0",
            "orgYearGU": gp["OrgYearGU"],
            "schoolID": school["SchoolID"],
            "markPeriodGU": focus_info["mark_period_gu"],
        }
    }

    try:
        r = session.post(
            f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
            json=payload,
            headers={**JSON_HEADERS, "AGU": "0"},
            timeout=15,
        )
        r.raise_for_status()
    except requests.Timeout:
        raise StudentVueError("Timed out fetching class list")
    except requests.RequestException as e:
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


def _load_class_control(
    session: requests.Session,
    focus_info: dict,
    cls: dict,
    student_gu: str,
    focus_key: str,
) -> None:
    """
    Replicates the browser's GB.LoadControl click handler — POSTs to LoadControl
    with the full FocusArgs (including classID) to set the server-side focus.
    After this call, GetClassData with Parameters '{}' returns that class's data.
    """
    school = focus_info["school"]
    gp = focus_info["grading_period"]

    payload = {
        "request": {
            "control": "Gradebook_ClassDetails",
            "parameters": {
                "viewName": None,
                "studentGU": student_gu,
                "schoolID": school["SchoolID"],
                "classID": cls["ID"],
                "markPeriodGU": focus_info["mark_period_gu"],
                "gradePeriodGU": gp["GU"],
                "subjectID": -1,
                "teacherID": -1,
                "assignmentID": -1,
                "standardIdentifier": None,
                "AGU": "0",
                "OrgYearGU": gp["OrgYearGU"],
                "gradingPeriodGroup": None,
            },
        }
    }

    r = session.post(
        f"{BASE_URL}/service/PXP2Communication.asmx/LoadControl",
        json=payload,
        headers={**JSON_HEADERS, "AGU": "0", "FOCUS_KEY": focus_key},
        timeout=15,
    )
    r.raise_for_status()


def get_class_grades(session: requests.Session, focus_key: str) -> dict:
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
        r = session.post(
            f"{BASE_URL}/api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData",
            json=payload,
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
    except requests.Timeout:
        raise StudentVueError("Timed out fetching class grades")
    except requests.RequestException as e:
        raise StudentVueError(f"Failed to fetch class grades: {e}")

    return r.json()


def _transform_assignment(a: dict) -> dict:
    """Transform a raw StudentVue assignment into the frontend Assignment shape."""
    score_str = a.get("score", "")
    points_possible = float(a.get("pointsPossible", 0) or 0)

    # Convert score to float (numeric scores only; skip letter/non-numeric)
    try:
        points_earned = float(score_str)
    except (ValueError, TypeError):
        # Non-numeric score (e.g. letter grade, "I", "C") — skip or zero
        points_earned = 0.0

    # Extra credit: x/0 — points go to earned only (no denominator)
    is_extra_credit = points_possible <= 0 and points_earned > 0

    # Build a readable title from available fields
    category = a.get("category") or a.get("unit") or "Assignment"
    due_date = a.get("dueDate", "")
    title = f"{category} — {due_date}" if due_date else category

    return {
        "id": str(a.get("resultID", "")),
        "title": title,
        "pointsEarned": points_earned,
        "pointsTotal": points_possible,
        "category": category,
        "dueDate": due_date,
        "excused": a.get("excused", False),
        "isForGrading": a.get("isForGrading", True),
        "isExtraCredit": is_extra_credit,
    }


def _transform_class(raw: dict) -> dict:
    """Transform a raw GetClassData response into the frontend ClassData shape."""
    students = raw.get("students", [])
    student = students[0] if students else {}

    assignments = [
        _transform_assignment(a)
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


def _fetch_period_classes(
    session: requests.Session,
    focus_data: dict,
    grading_period: dict,
    student_gu: str,
) -> tuple[list[dict], list[dict | None]]:
    """
    For a single grading period: call GradebookFocusClassInfo to get FOCUS_KEY + class list,
    then LoadControl + GetClassData for each class.
    Returns (classes, raw_grade_data_list) — parallel lists, raw entries may be None on failure.
    """
    school = focus_data["Schools"][0]
    mark_periods = grading_period.get("MarkPeriods", [])
    mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""

    r = session.post(
        f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
        json={"request": {
            "gradingPeriodGU": grading_period["GU"],
            "AGU": "0",
            "orgYearGU": grading_period["OrgYearGU"],
            "schoolID": school["SchoolID"],
            "markPeriodGU": mark_period_gu,
        }},
        headers={**JSON_HEADERS, "AGU": "0"},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json().get("d", {})
    focus_key = d.get("FOCUS_KEY", "")
    classes = d.get("Data", {}).get("Classes", [])

    focus_info = {
        "school": school,
        "grading_period": grading_period,
        "mark_period_gu": mark_period_gu,
    }

    raw_list = []
    for cls in classes:
        try:
            _load_class_control(session, focus_info, cls, student_gu, focus_key)
            raw_list.append(get_class_grades(session, focus_key))
        except Exception:
            raw_list.append(None)

    return classes, raw_list


def scrape(username: str, password: str) -> dict:
    """
    Full pipeline: login → gradebook config → all Regular marking periods → per-class grades.
    Returns a dict with 'student', 'gradingPeriods', and 'classes' keys.
    Each class has a 'markingPeriods' list with per-period assignment data.
    Raises LoginError, StudentVueError, or ParseError on failure.
    """
    session = login(username, password)
    focus_data = get_gradebook_config(session)
    student_gu = focus_data.get("_studentGU", "0")

    schools = focus_data.get("Schools", [])
    if not schools:
        raise ParseError("No schools in GBFocusData")

    school = schools[0]
    all_periods = school.get("GradingPeriods", [])

    # Fetch Regular marking periods only (skip Semester Term summary periods)
    regular_periods = [gp for gp in all_periods if gp.get("GroupName") == "Regular"]
    if not regular_periods:
        regular_periods = all_periods

    # Fetch per-period data; collect results keyed by classId
    # Structure: {classId: {periodName: raw_data}}
    class_period_data: dict[int, dict[str, dict]] = {}
    class_meta: dict[int, dict] = {}  # ID → {Name, TeacherName}
    student_name = None
    period_names = []

    for gp in regular_periods:
        period_name = gp["Name"]
        period_names.append(period_name)
        try:
            classes_for_period, raw_list = _fetch_period_classes(session, focus_data, gp, student_gu)
        except Exception:
            continue  # skip failed periods entirely

        for cls, raw in zip(classes_for_period, raw_list):
            cid = cls["ID"]
            class_meta[cid] = cls
            if cid not in class_period_data:
                class_period_data[cid] = {}
            class_period_data[cid][period_name] = raw

            if student_name is None and raw:
                students = raw.get("students", [])
                if students:
                    student_name = students[0].get("name")

    # Build final classes list
    all_class_data = []
    for cid, periods in class_period_data.items():
        meta = class_meta.get(cid, {})
        marking_periods = []

        period_id_sets: dict[str, set[str]] = {}
        for pname in period_names:
            raw = periods.get(pname)
            if raw:
                assignments = [
                    _transform_assignment(a)
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

        # Determine current period (defaultFocus) and overall grade
        default_period = next(
            (gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1]
        )
        current_mp = periods.get(default_period["Name"])
        current_students = (current_mp or {}).get("students", [])
        current_student = current_students[0] if current_students else {}
        current_mp_marking = next(
            (mp for mp in marking_periods if mp["label"] == default_period["Name"]),
            marking_periods[-1] if marking_periods else {},
        )

        all_class_data.append({
            "id": str(cid),
            "name": _clean_class_name(meta.get("Name", "")),
            "teacherName": meta.get("TeacherName", ""),
            "gradingType": grading_type,
            "percentage": current_student.get("percentage"),
            "calculatedMark": current_student.get("calculatedMark"),
            "currentPeriod": default_period["Name"],
            "markingPeriods": marking_periods,
            "isAssignmentWeightingOn": current_mp_marking.get("isAssignmentWeightingOn", False),
            "assignmentCategories": current_mp_marking.get("assignmentCategories", []),
            # Convenience: current period assignments at top level for frontend compat
            "assignments": next(
                (mp["assignments"] for mp in marking_periods if mp["label"] == default_period["Name"]),
                [],
            ),
        })

    return {
        "student": {"name": student_name},
        "periods": period_names,
        "classes": all_class_data,
    }
