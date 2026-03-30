#!/usr/bin/env python3
"""
StudentVue Web Scraper — Midland Public Schools
Replicates the PXP2 web portal login flow and fetches gradebook data.

Auth flow:
  1. GET login page → extract __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
  2. POST login with credentials + ASP.NET tokens → get session cookie
  3. GET gradebook page → extract GBFocusData (GUIDs for grading periods)
  4. POST /service/PXP2Communication.asmx/GradebookFocusClassInfo → class list
  5. POST /api/GB/ClientSideData/Transfer → per-class grade data
"""

import requests
import re
import json
import sys
from html import unescape
from urllib.parse import urljoin

BASE_URL = "https://mi-mps.edupoint.com"
LOGIN_URL = f"{BASE_URL}/PXP2_Login_Student.aspx?regenerateSessionId=true"

# Standard browser headers
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


def login(username, password):
    """
    Step 1-2: GET login page for ASP.NET tokens, then POST credentials.
    Returns a requests.Session with the authenticated session cookie.
    """
    session = requests.Session()

    # Step 1: GET the login page to extract hidden form fields
    print("[1/5] Fetching login page...")
    r = session.get(LOGIN_URL, headers=BROWSER_HEADERS, timeout=15)
    r.raise_for_status()

    # Extract ASP.NET hidden fields
    viewstate = re.search(r'id="__VIEWSTATE"\s+value="([^"]*)"', r.text)
    viewstate_gen = re.search(r'id="__VIEWSTATEGENERATOR"\s+value="([^"]*)"', r.text)
    event_validation = re.search(r'id="__EVENTVALIDATION"\s+value="([^"]*)"', r.text)

    if not viewstate or not event_validation:
        print("  ❌ Could not extract ASP.NET form tokens from login page")
        print(f"  Page title: {re.search(r'<title>(.*?)</title>', r.text, re.I)}")
        return None

    print(f"  ✅ Got VIEWSTATE ({len(viewstate.group(1))} chars)")

    # Step 2: POST login
    print(f"[2/5] Logging in as {username}...")
    form_data = {
        "__VIEWSTATE": viewstate.group(1),
        "__VIEWSTATEGENERATOR": viewstate_gen.group(1) if viewstate_gen else "",
        "__EVENTVALIDATION": event_validation.group(1),
        "ctl00$MainContent$username": username,
        "ctl00$MainContent$password": password,
        "ctl00$MainContent$Submit1": "Login",
    }

    r = session.post(
        LOGIN_URL,
        data=form_data,
        headers={**BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
        allow_redirects=True,
    )

    # Check if login succeeded (should redirect to Home_PXP2.aspx)
    if "Home_PXP2.aspx" in r.url or "Home_PXP2" in r.text:
        print(f"  ✅ Login successful! Redirected to {r.url}")
    elif "login" in r.url.lower():
        print("  ❌ Login failed — still on login page")
        # Try to find error message
        err = re.search(r'ErrorMessage["\s>]+([^<]+)', r.text)
        if err:
            print(f"  Error: {err.group(1)}")
        return None
    else:
        print(f"  ⚠️  Ended up at {r.url} — check if logged in")

    print(f"  Session cookies: {dict(session.cookies)}")
    return session


def get_gradebook_config(session):
    """
    Step 3: Load the gradebook page and extract GBFocusData
    (contains grading period GUIDs, school ID, org year, etc.)
    """
    print("[3/5] Loading gradebook page...")

    # First we need the studentGU — get it from the home page/student summary
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

    student_gu = None
    if r.status_code == 200:
        gu_match = re.search(r'"studentGU":"([^"]+)"', r.text)
        if gu_match:
            student_gu = gu_match.group(1)
            print(f"  ✅ Student GU: {student_gu}")

    if not student_gu:
        print("  ⚠️  Could not extract studentGU, trying gradebook page directly...")
        student_gu = "0"

    # Load gradebook page
    gb_url = f"{BASE_URL}/PXP2_Gradebook.aspx?AGU=0&studentGU={student_gu}"
    r = session.get(gb_url, headers=BROWSER_HEADERS, timeout=15)

    # Extract GBFocusData JSON blob
    match = re.search(r'PXP\.GBFocusData\s*=\s*(\{.*?\});\s*\n', r.text, re.DOTALL)
    if not match:
        # Try a broader match
        match = re.search(r'GBFocusData\s*=\s*(\{.+?\});\s', r.text, re.DOTALL)

    if not match:
        print("  ❌ Could not find GBFocusData in gradebook page")
        return None

    try:
        focus_data = json.loads(match.group(1))
        print(f"  ✅ Got GBFocusData!")
        schools = focus_data.get("Schools", [])
        for school in schools:
            print(f"  School: {school.get('SchoolName')}")
            for gp in school.get("GradingPeriods", []):
                print(f"    {gp['Name']} (GU: {gp['GU'][:8]}..., default: {gp.get('defaultFocus', False)})")
        return focus_data
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse GBFocusData: {e}")
        return None


def get_class_list(session, focus_data):
    """
    Step 4: Get the list of classes for the current/default grading period.
    """
    print("[4/5] Fetching class list...")

    # Find the default grading period (or use the last one = current)
    schools = focus_data.get("Schools", [])
    if not schools:
        print("  ❌ No schools in focus data")
        return None

    school = schools[0]
    grading_periods = school.get("GradingPeriods", [])

    # Find the default or pick the last regular one
    target_gp = None
    for gp in grading_periods:
        if gp.get("defaultFocus"):
            target_gp = gp
            break

    if not target_gp:
        # Pick the last "Regular" grading period
        regular_gps = [gp for gp in grading_periods if gp.get("GroupName") == "Regular"]
        target_gp = regular_gps[-1] if regular_gps else grading_periods[-1]

    mark_periods = target_gp.get("MarkPeriods", [])
    mark_period_gu = mark_periods[0]["GU"] if mark_periods else ""

    print(f"  Using: {target_gp['Name']} (GU: {target_gp['GU'][:8]}...)")

    payload = {
        "request": {
            "gradingPeriodGU": target_gp["GU"],
            "AGU": "0",
            "orgYearGU": target_gp["OrgYearGU"],
            "schoolID": school["SchoolID"],
            "markPeriodGU": mark_period_gu,
        }
    }

    r = session.post(
        f"{BASE_URL}/service/PXP2Communication.asmx/GradebookFocusClassInfo",
        json=payload,
        headers={**JSON_HEADERS, "AGU": "0"},
        timeout=15,
    )

    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        return None

    data = r.json()
    d = data.get("d", {})
    classes = d.get("Data", {}).get("Classes", [])
    focus_key = d.get("FOCUS_KEY", "")

    print(f"  ✅ Got {len(classes)} classes (FOCUS_KEY: {focus_key[:8]}...)")
    for c in classes:
        print(f"    • {c['Name']} — {c['TeacherName']} (ID: {c['ID']})")

    return {"classes": classes, "focus_key": focus_key}


def get_class_grades(session, focus_key):
    """
    Step 5: Fetch detailed grade data for the currently focused class.
    The FOCUS_KEY tells the server which grading period context we're in.
    """
    print("[5/5] Fetching grade data...")

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

    r = session.post(
        f"{BASE_URL}/api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData",
        json=payload,
        headers=headers,
        timeout=15,
    )

    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        return None

    data = r.json()
    print(f"  ✅ Got grade data for: {data.get('className', 'unknown')}")
    print(f"  Grading period: {data.get('GradingPeriodName', 'unknown')}")

    students = data.get("students", [])
    for s in students:
        print(f"  Student: {s.get('name')}")
        print(f"    Mark: {s.get('calculatedMark')} ({s.get('percentage')}%)")

    # Show assignment categories/weights
    categories = data.get("assignmentCategories", [])
    for cat in categories:
        print(f"    Category: {cat.get('name')} (weight: {cat.get('weight')})")

    # Show assignments
    assignments = data.get("assignments", [])
    if assignments:
        print(f"    Assignments ({len(assignments)} total):")
        for a in assignments[:10]:  # Show first 10
            score = a.get("score", "")
            points = a.get("points", "")
            name = a.get("name", "")
            print(f"      - {name}: {score} ({points})")
        if len(assignments) > 10:
            print(f"      ... and {len(assignments) - 10} more")

    return data


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 scraper.py USERNAME PASSWORD")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    print(f"\n{'='*60}")
    print(f" StudentVue Web Scraper — Midland Public Schools")
    print(f"{'='*60}\n")

    # Step 1-2: Login
    session = login(username, password)
    if not session:
        print("\n❌ Login failed. Exiting.")
        sys.exit(1)

    # Step 3: Get gradebook config
    focus_data = get_gradebook_config(session)
    if not focus_data:
        print("\n❌ Could not get gradebook config. Exiting.")
        sys.exit(1)

    # Step 4: Get class list
    result = get_class_list(session, focus_data)
    if not result:
        print("\n❌ Could not get class list. Exiting.")
        sys.exit(1)

    # Step 5: Get grades for the default class
    grade_data = get_class_grades(session, result["focus_key"])

    print(f"\n{'='*60}")
    if grade_data:
        print(" ✅ SUCCESS — Full auth + data pipeline works!")
        print(f"\n Raw grade data saved to: grades_output.json")
        with open("grades_output.json", "w") as f:
            json.dump(grade_data, f, indent=2)
    else:
        print(" ⚠️  Got classes but grade data fetch failed")
    print(f"{'='*60}\n")
