"""
GradesView FastAPI Backend
Proxies StudentVue grade data for the React frontend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal

from pydantic import BaseModel

from scraper import scrape, scrape_class_detail, LoginError, StudentVueError, ParseError

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
