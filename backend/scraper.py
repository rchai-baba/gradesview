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

import hashlib
import json
import re
import requests
from collections import defaultdict
from html import unescape
from pathlib import Path

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


def _load_class_control_raw_html(
    session: requests.Session,
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
    return r.json().get("d", {}).get("Data", {}).get("html", "")


def _load_class_control(
    session: requests.Session,
    focus_info: dict,
    cls: dict,
    student_gu: str,
    focus_key: str,
) -> dict[int, str]:
    """
    Replicates the browser's GB.LoadControl click handler — POSTs to LoadControl
    with the full FocusArgs (including classID) to set the server-side focus.
    After this call, GetClassData with Parameters '{}' returns that class's data.
    Also parses assignment titles from the HTML response.
    Returns {gradeBookId: title} map (may be empty if HTML has no assignments).
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

    try:
        html = r.json().get("d", {}).get("Data", {}).get("html", "")
        return _parse_titles_from_html(html)
    except Exception:
        return {}


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
            title_map = _load_class_control(session, focus_info, cls, student_gu, focus_key)
            raw = get_class_grades(session, focus_key)
            raw["_titleMap"] = title_map  # attach so _transform_assignment can use it
            raw_list.append(raw)
        except Exception:
            raw_list.append(None)

    return classes, raw_list


def scrape_cards_only(username: str, password: str) -> dict:
    """
    Fast path: one GradebookFocusClassInfo (default period) — no GetClassData per class.
    Grades come from class-row hints when Synergy exposes them; otherwise null until /api/class-detail.
    """
    session = login(username, password)
    focus_data = get_gradebook_config(session)
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

    cls_list = get_class_list(session, focus_data)
    classes = cls_list["classes"]
    default_focus = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
    default_name = default_focus["Name"]

    class_period_data: dict[int, dict[str, dict]] = {}
    class_meta: dict[int, dict] = {}

    for cls in classes:
        cid = cls["ID"]
        class_meta[cid] = cls
        pct, letter = _class_focus_grade_hints(cls)
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


def scrape_class_detail(
    username: str,
    password: str,
    marking_period: str,
    synergy_class_ids: list[int],
) -> dict:
    """One class + one marking period: GradebookFocusClassInfo → LoadControl → GetClassData."""
    if not synergy_class_ids:
        raise ParseError("synergyClassIds required")

    session = login(username, password)
    focus_data = get_gradebook_config(session)
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
    focus_info = {
        "school": school,
        "grading_period": gp,
        "mark_period_gu": mark_period_gu,
    }

    r = session.post(
        f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
        json={"request": {
            "gradingPeriodGU": gp["GU"],
            "AGU": "0",
            "orgYearGU": gp["OrgYearGU"],
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

    last_err: Exception | None = None
    raw: dict | None = None
    used_cls: dict | None = None
    for cid in synergy_class_ids:
        cls = next((c for c in classes if c["ID"] == cid), None)
        if not cls:
            continue
        try:
            title_map = _load_class_control(session, focus_info, cls, student_gu, focus_key)
            raw = get_class_grades(session, focus_key)
            raw["_titleMap"] = title_map
            used_cls = cls
            break
        except Exception as e:
            last_err = e

    if raw is None:
        raise StudentVueError(f"Could not load class detail: {last_err}")

    # Short, safe dump of raw data for debugging
    import json
    with open("debug_raw.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(raw, indent=2)[:5000])
    print("Preview saved to debug_raw.json")

    # Map metadata by assignmentID for quick lookup
    meta_map = {
        str(m.get("assignmentID", m.get("AssignmentID", ""))): m
        for m in (raw.get("Assignments") or [])
    }

    # Merge metadata into score records before transforming
    assignments = []
    for a in raw.get("assignments", []):
        if not a.get("isForGrading", True) or a.get("hideInPortal", False):
            continue
        aid = str(a.get("assignmentID", a.get("AssignmentID", "")))
        if aid in meta_map:
            # Merge: metadata into score object
            a = {**a, **meta_map[aid]}
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


def scrape(username: str, password: str, *, fetch_mode: str = "full") -> dict:
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

    if fetch_mode == "cards_only":
        return scrape_cards_only(username, password)

    cfg = _load_course_merge_config()
    merge_groups: tuple[frozenset[str], ...] = cfg["mergeNameGroups"]
    semester_groups: list[list[str]] = cfg["semesterGroups"]

    if fetch_mode == "current_period_only":
        default_gp = next((gp for gp in regular_periods if gp.get("defaultFocus")), regular_periods[-1])
        regular_periods = [default_gp]

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

            # Short, safe dump of raw data for debugging (first class that has data)
            import os, json
            if not os.path.exists("debug_raw.json") and raw:
                with open("debug_raw.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(raw, indent=2)[:5000])
                print("Initial sync preview saved to debug_raw.json")

            if student_name is None and raw:
                students = raw.get("students", [])
                if students:
                    student_name = students[0].get("name")

    merged_period_data, merged_class_meta, merged_sources = _merge_semester_split_rows(
        class_period_data, class_meta, period_names, merge_groups
    )

    # Build final classes list
    all_class_data = []
    for public_id, periods in merged_period_data.items():
        meta = merged_class_meta.get(public_id, {})
        marking_periods = []

        period_id_sets: dict[str, set[str]] = {}
        for pname in period_names:
            raw = periods.get(pname)
            if raw:
                # Map metadata by assignmentID for quick lookup
                meta_map = {
                    str(m.get("assignmentID", m.get("AssignmentID", ""))): m
                    for m in (raw.get("Assignments") or [])
                }

                # Merge metadata into score records before transforming
                assignments = []
                for a in raw.get("assignments", []):
                    if not a.get("isForGrading", True) or a.get("hideInPortal", False):
                        continue
                    aid = str(a.get("assignmentID", a.get("AssignmentID", "")))
                    if aid in meta_map:
                        # Merge metadata into score object
                        a = {**a, **meta_map[aid]}
                    assignments.append(_transform_assignment(a, raw.get("_titleMap")))

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
                    "assignmentsLoaded": True,
                })
            else:
                marking_periods.append({
                    "label": pname,
                    "percentage": None,
                    "calculatedMark": None,
                    "assignments": [],
                    "isAssignmentWeightingOn": False,
                    "assignmentCategories": [],
                    "assignmentsLoaded": True,
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
            "currentPeriod": default_period["Name"],
            "markingPeriods": marking_periods,
            "isAssignmentWeightingOn": current_mp_marking.get("isAssignmentWeightingOn", False),
            "assignmentCategories": current_mp_marking.get("assignmentCategories", []),
            # Convenience: current period assignments at top level for frontend compat
            "assignments": next(
                (mp["assignments"] for mp in marking_periods if mp["label"] == default_period["Name"]),
                [],
            ),
            "assignmentsLoaded": True,
        }
        src = merged_sources.get(public_id, [])
        if len(src) > 1:
            row["mergedFromIds"] = [str(x) for x in src]
        all_class_data.append(row)

    all_class_data.sort(key=lambda c: (c.get("name") or "").lower())

    out = {
        "student": {"name": student_name},
        "periods": period_names,
        "classes": all_class_data,
        "semesterGroups": semester_groups,
        "fetchMode": fetch_mode,
    }

    # Save full dump of all transformed assignments for external verification
    debug_list = []
    for cls_row in all_class_data:
        for p in cls_row.get("markingPeriods", []):
            for a in p.get("assignments", []):
                debug_list.append({
                    "class": cls_row["name"],
                    "period": p["label"],
                    "title": a["title"],
                    "category": a["category"],
                    "earned": a["pointsEarned"],
                    "total": a["pointsTotal"],
                    "excused": a["excused"],
                    "raw_id": a["id"],
                    "raw_debug": a.get("debugFields")
                })
    with open("debug_assignments.json", "w", encoding="utf-8") as f:
        json.dump(debug_list, f, indent=2)

    return out
