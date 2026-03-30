# GradesView — Auth Flow Notes

## Base URL
https://mi-mps.edupoint.com

## Why not SOAP?
The SOAP API (PXPCommunication.asmx) rejects all requests with error
"UPD5304 - You must update app to the new version to continue."
Every User-Agent string we tried (old app, new app, browser, empty) gets rejected.
The server is checking for the new StudentVUE app (com.edupoint.studentvue) which
likely sends additional headers or uses a different protocol entirely.

## What we do instead
We replicate the PXP2 web portal browser session. The web portal still works
with username/password auth (legacy, not Microsoft SSO).

## Auth Flow (5 steps)

1. GET /PXP2_Login_Student.aspx → extract __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
2. POST login with credentials + ASP.NET tokens → get ASP.NET_SessionId cookie, 302 to /Home_PXP2.aspx
3. POST /Service/RTCommunication.asmx/XMLDoRequest → get studentGU
   GET /PXP2_Gradebook.aspx → extract PXP.GBFocusData JSON from HTML (grading period GUIDs)
4. POST /service/PXP2Communication.asmx/GradebookFocusClassInfo → class list + FOCUS_KEY
5. POST /api/GB/ClientSideData/Transfer?action=genericdata.classdata-GetClassData → grade data per class
   Required headers: FOCUS_KEY, CURRENT_WEB_PORTAL: StudentVUE, X-Requested-With: XMLHttpRequest

## Key details
- Auth is session cookie based (ASP.NET_SessionId)
- GUIDs for grading periods, org year, etc. are extracted dynamically from the gradebook page
- FOCUS_KEY is a per-session token returned by step 4, required for step 5
- Grade data includes: class name, percentage, letter grade, assignment categories with weights,
  individual assignments with scores, and the full grading scale

## Known issue
- Step 5 currently only returns data for the default class
- Need to figure out how to switch between classes (check HAR for class-switching requests)

## Grading scale (from response data)
A  = 93.00 - 100.00
A- = 90.00 - 92.99
B+ = 87.00 - 89.99
B  = 83.00 - 86.99
B- = 80.00 - 82.99
C+ = 77.00 - 79.99
C  = 73.00 - 76.99
C- = 70.00 - 72.99
D+ = 67.00 - 69.99
D  = 63.00 - 66.99
D- = 60.00 - 62.99
E  = 0.00  - 59.99
