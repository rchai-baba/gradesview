# GradesView — Auth Flow Notes

## Base URL
https://mi-mps.edupoint.com

## Auth Flow (web scraping, NOT SOAP)
The SOAP API (PXPCommunication.asmx) is dead — rejects all 
User-Agents with UPD5304. We use the PXP2 web portal instead.

1. GET /PXP2_Login_Student.aspx → extract __VIEWSTATE, __EVENTVALIDATION
2. POST credentials → get ASP.NET_SessionId cookie
3. GET /PXP2_Gradebook.aspx → extract PXP.GBFocusData (JSON in HTML)
4. POST /service/PXP2Communication.asmx/GradebookFocusClassInfo → class list + FOCUS_KEY
5. POST /api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData → grade data
   - Requires headers: FOCUS_KEY, CURRENT_WEB_PORTAL: StudentVUE

## Key endpoints
- Login: POST /PXP2_Login_Student.aspx?regenerateSessionId=true
- Student summary: POST /Service/RTCommunication.asmx/XMLDoRequest?PORTAL=StudentVUE  
- Class list: POST /service/PXP2Communication.asmx/GradebookFocusClassInfo
- Grade data: POST /api/GB/ClientSideData/Transfer

## TODO
- Fetch grades for ALL classes (not just default)
- What-if grade calculator
