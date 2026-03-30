"""
GradesView FastAPI Backend
Proxies StudentVue grade data for the React frontend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import scrape, LoginError, StudentVueError, ParseError

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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/login")
def api_login(body: LoginRequest):
    from fastapi.responses import JSONResponse

    try:
        data = scrape(body.username, body.password)
        return JSONResponse(content=data)
    except LoginError:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
    except StudentVueError:
        return JSONResponse(status_code=502, content={"error": "StudentVue is not responding"})
    except ParseError as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to parse grade data: {e}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {e}"})
