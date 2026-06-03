"""
Test POST /api/login with fetch_mode=cards_only.
All outbound HTTP calls to mi-mps.edupoint.com are intercepted by respx.
"""
import json
import pytest
import respx
from httpx import AsyncClient, Response

from backend.main import app


LOGIN_HTML = """
<html>
<input id="__VIEWSTATE" value="VS123" />
<input id="__VIEWSTATEGENERATOR" value="VSG456" />
<input id="__EVENTVALIDATION" value="EV789" />
</html>
"""

# Simulates a successful login redirect to Home_PXP2.aspx
LOGIN_REDIRECT_HTML = "<html>Home_PXP2.aspx login successful</html>"

STUDENT_SUMMARY_JSON = json.dumps({"studentGU": "stu-guid-001"})

GRADEBOOK_HTML = """
<html><script>
PXP.GBFocusData = {"Schools":[{"SchoolID":"101","GradingPeriods":[{
  "Name":"MP1","GU":"gp-gu-1","OrgYearGU":"oy-gu-1","GroupName":"Regular",
  "defaultFocus":true,
  "MarkPeriods":[{"GU":"mp-gu-1"}]
}]}]};
</script></html>
"""

FOCUS_CLASS_INFO = {
    "d": {
        "FOCUS_KEY": "fk-abc",
        "Data": {
            "Classes": [
                {"ID": 42, "Name": "Smith, J  AP Chemistry H (1 hr)(3) SEC:SC100-1", "TeacherName": "Smith, J"}
            ]
        },
    }
}

LOAD_CONTROL_RESPONSE = {
    "d": {
        "Data": {
            "html": """
            <div id="current-grade">
              <div class="mark">A</div>
              <div class="score">95.5%</div>
            </div>
            """
        }
    }
}

BASE = "https://mi-mps.edupoint.com"


@pytest.mark.asyncio
@respx.mock
async def test_login_cards_only_returns_classes():
    # Step 1: GET login page
    respx.get(f"{BASE}/PXP2_Login_Student.aspx").mock(
        return_value=Response(200, text=LOGIN_HTML)
    )
    # Step 2: POST credentials → success (contains Home_PXP2.aspx marker)
    respx.post(f"{BASE}/PXP2_Login_Student.aspx").mock(
        return_value=Response(200, text=LOGIN_REDIRECT_HTML, headers={"Set-Cookie": "ASP.NET_SessionId=abc123"})
    )
    # Step 3a: RTCommunication for studentGU
    respx.post(f"{BASE}/Service/RTCommunication.asmx/XMLDoRequest").mock(
        return_value=Response(200, text=STUDENT_SUMMARY_JSON)
    )
    # Step 3b: GET gradebook page
    respx.get(url__regex=r".*/PXP2_Gradebook\.aspx.*").mock(
        return_value=Response(200, text=GRADEBOOK_HTML)
    )
    # Step 4: GradebookFocusClassInfo
    respx.post(f"{BASE}/service/PXP2Communication.asmx/GradebookFocusClassInfo").mock(
        return_value=Response(200, json=FOCUS_CLASS_INFO)
    )
    # Step 5 (cards_only): LoadControl for grade card HTML
    respx.post(f"{BASE}/service/PXP2Communication.asmx/LoadControl").mock(
        return_value=Response(200, json=LOAD_CONTROL_RESPONSE)
    )

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/api/login",
            json={"username": "student1", "password": "pass", "fetch_mode": "cards_only"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["fetchMode"] == "cards_only"
    assert len(data["classes"]) == 1
    assert data["classes"][0]["name"] == "AP Chemistry H"
    assert data["classes"][0]["percentage"] == 95.5
    assert data["classes"][0]["calculatedMark"] == "A"
