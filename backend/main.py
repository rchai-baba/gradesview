"""
GradesView FastAPI Backend
Proxies StudentVue grade data for the React frontend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal

from pydantic import BaseModel

from scraper import (
    scrape, scrape_class_detail, LoginError, StudentVueError, ParseError,
    login, get_gradebook_config, get_class_list, get_class_grades,
    _load_class_control_raw_html, _get_focus_info,
)

app = FastAPI(title="GradesView API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str
    """cards_only = fast grid (no per-class GetClassData). current_period_only / full = load assignments on login."""
    fetch_mode: Literal["full", "current_period_only", "cards_only"] = "cards_only"


class ClassDetailRequest(BaseModel):
    username: str
    password: str
    markingPeriod: str
    synergyClassIds: list[int]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/login")
def api_login(body: LoginRequest):
    from fastapi.responses import JSONResponse

    try:
        data = scrape(body.username, body.password, fetch_mode=body.fetch_mode)
        return JSONResponse(content=data)
    except LoginError:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except StudentVueError:
        return JSONResponse(status_code=502, content={"error": "StudentVue is not responding"})
    except ParseError as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to parse grade data: {e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {e}"})


@app.post("/api/debug/loadcontrol-html")
def debug_loadcontrol_html(body: LoginRequest):
    """Debug endpoint: returns raw LoadControl HTML for the first class so we can inspect its structure."""
    from fastapi.responses import JSONResponse

    try:
        session = login(body.username, body.password)
        focus_data = get_gradebook_config(session)
        class_list = get_class_list(session, focus_data)
        focus_info = class_list["focus_info"]
        focus_key = class_list["focus_key"]
        classes = class_list["classes"]
        student_gu = focus_data.get("_studentGU", "0")

        import re as _re

        results = []
        for cls in classes[:1]:  # just first class for detailed inspection
            raw_html = _load_class_control_raw_html(session, focus_info, cls, student_gu, focus_key)
            raw_grades = get_class_grades(session, focus_key)
            assignments_sample = raw_grades.get("assignments", [])[:5]

            # Search for data-focus occurrences and extract samples
            data_focus_matches = _re.findall(r'data-focus=["\'](\{[^"\']{0,300})["\']', raw_html)
            assignment_id_count = len(_re.findall(r'assignmentID', raw_html))
            data_focus_count = len(_re.findall(r'data-focus', raw_html))

            # Find all lines containing "data-focus" for inspection
            lines_with_focus = []
            for i, line in enumerate(raw_html.splitlines()):
                if "data-focus" in line:
                    lines_with_focus.append({"line": i, "content": line[:500]})

            results.append({
                "classID": cls.get("ID"),
                "className": cls.get("Name") or cls.get("CourseTitle"),
                "html_length": len(raw_html),
                "data_focus_count": data_focus_count,
                "assignment_id_count": assignment_id_count,
                "data_focus_samples": data_focus_matches[:10],
                "lines_with_focus": lines_with_focus[:20],
                "assignments_sample_gradeBookIds": [a.get("gradeBookId") for a in assignments_sample],
                "html_tail": raw_html[-3000:],  # end of HTML often has the assignment table
            })

        return JSONResponse(content={"results": results})
    except LoginError:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"{type(e).__name__}: {e}"})


@app.post("/api/debug/raw-assignment")
def debug_raw_assignment(body: LoginRequest):
    """Returns the full raw GetClassData JSON for the first class (unfiltered)."""
    from fastapi.responses import JSONResponse

    try:
        session = login(body.username, body.password)
        focus_data = get_gradebook_config(session)
        class_list = get_class_list(session, focus_data)
        focus_info = class_list["focus_info"]
        focus_key = class_list["focus_key"]
        classes = class_list["classes"]
        student_gu = focus_data.get("_studentGU", "0")

        cls = classes[0]
        _load_class_control_raw_html(session, focus_info, cls, student_gu, focus_key)
        raw_grades = get_class_grades(session, focus_key)

        return JSONResponse(content={
            "classID": cls.get("ID"),
            "className": cls.get("Name") or cls.get("CourseTitle"),
            "raw_grades": raw_grades,
        })
    except LoginError:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"{type(e).__name__}: {e}"})


@app.post("/api/class-detail")
def api_class_detail(body: ClassDetailRequest):
    from fastapi.responses import JSONResponse

    try:
        data = scrape_class_detail(
            body.username,
            body.password,
            body.markingPeriod,
            body.synergyClassIds,
        )
        return JSONResponse(content=data)
    except LoginError:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except StudentVueError as e:
        return JSONResponse(status_code=502, content={"error": str(e) or "StudentVue is not responding"})
    except ParseError as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to load class: {e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {e}"})
