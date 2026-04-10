#!/usr/bin/env python3
"""
StudentVue SOAP API — User-Agent Brute Force Test
Your district's server rejects the old app UA (StudentVUE/8.0.26) with UPD5304.
This script tries multiple User-Agent strings to find what gets through.
"""

import requests
import sys
import xml.sax.saxutils as saxutils

BASE_HOST = "mi-mps.edupoint.com"
SOAP_ENDPOINT = f"https://{BASE_HOST}/Service/PXPCommunication.asmx"

# User-Agents to try — ordered from most likely to work
USER_AGENTS = [
    # 1. New StudentVUE app (iOS) — high version number
    ("New iOS App v20.0",      "StudentVUE/20.0.0 CFNetwork/1568.200.51 Darwin/24.1.0"),
    # 2. Latest known iOS version
    ("Latest iOS App v11.3.1", "StudentVUE/11.3.1 CFNetwork/1404.0.5 Darwin/22.3.0"),
    # 3. New StudentVUE app (Android)
    ("New Android App v11.1.0", "StudentVUE/11.1.0 (Linux; Android 14)"),
    # 4. Try the Synergy 2026 era version
    ("Android App v11.1.0 (Pixel)", "StudentVUE/11.1.0 (Linux; Android 14; Pixel 7)"),
    # 5. Generic mobile browser (maybe no UA check for non-app agents?)
    ("Generic Chrome Mobile",  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
    # 6. Plain python requests default  
    ("Python Requests default", None),
    # 7. No user-agent at all
    ("Empty UA",               ""),
    # 8. Old app version for comparison (should fail)
    ("Old App v8.0.26",        "StudentVUE/8.0.26 CFNetwork/1121.2.2 Darwin/19.3.0"),
]


def build_soap_envelope(user_id, password, method_name, param_str):
    u = saxutils.escape(user_id)
    p = saxutils.escape(password)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ProcessWebServiceRequest xmlns="http://edupoint.com/webservices/">
      <userID>{u}</userID>
      <password>{p}</password>
      <skipLoginLog>1</skipLoginLog>
      <parent>0</parent>
      <webServiceHandleName>PXPWebServices</webServiceHandleName>
      <methodName>{method_name}</methodName>
      <paramStr>{param_str}</paramStr>
    </ProcessWebServiceRequest>
  </soap:Body>
</soap:Envelope>"""


def test_ua(label, user_agent, username, password):
    """Test a single User-Agent string."""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://edupoint.com/webservices/ProcessWebServiceRequest",
    }
    if user_agent is not None:
        headers["User-Agent"] = user_agent

    body = build_soap_envelope(
        user_id=username,
        password=password,
        method_name="Gradebook",
        param_str="&lt;Parms&gt;&lt;ChildIntID&gt;0&lt;/ChildIntID&gt;&lt;/Parms&gt;",
    )

    try:
        r = requests.post(SOAP_ENDPOINT, data=body, headers=headers, timeout=15)
        response_text = r.text

        if "UPD5304" in response_text or "update app" in response_text.lower():
            status = "❌ REJECTED (UPD5304 upgrade error)"
        elif "Invalid" in response_text or "invalid" in response_text:
            status = "❌ INVALID CREDENTIALS"
        elif "RT_ERROR" in response_text:
            # Extract error message
            import re
            match = re.search(r'ERROR_MESSAGE="([^"]*)"', response_text)
            err_msg = match.group(1) if match else "unknown error"
            status = f"⚠️  ERROR: {err_msg}"
        elif "Gradebook" in response_text or "Course" in response_text:
            status = "✅ SUCCESS — GOT GRADEBOOK DATA!"
        elif r.status_code == 200:
            status = "⚠️  200 OK but unclear response"
        else:
            status = f"❌ HTTP {r.status_code}"

        print(f"  [{label:.<30s}] {status}")

        # If we got data, print a preview
        if "SUCCESS" in status:
            print(f"\n  🎉 WORKING USER-AGENT: {user_agent}")
            print(f"\n  --- Response preview (first 2000 chars) ---")
            print(response_text[:2000])
            return True
        elif "unclear" in status:
            print(f"      Preview: {response_text[:300]}")

    except Exception as e:
        print(f"  [{label:.<30s}] ❌ ERROR: {e}")

    return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 test_ua.py USERNAME PASSWORD")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    print(f"\n🔍 Testing User-Agent strings against {SOAP_ENDPOINT}")
    print(f"   Username: {username}")
    print(f"   Method: Gradebook")
    print("=" * 70)

    found = False
    for label, ua in USER_AGENTS:
        if test_ua(label, ua, username, password):
            found = True
            break

    if not found:
        print("\n" + "=" * 70)
        print("❌ None of the User-Agent strings worked.")
        print()
        print("Next steps to try:")
        print("  1. Install the StudentVUE app on your phone")
        print("  2. Use mitmproxy/Charles to intercept the actual request")
        print("  3. Copy the exact User-Agent header from the working request")
        print("  4. Also look for any other headers the new app sends")
        print()
        print("The new app might also send additional headers beyond User-Agent")
        print("(like a custom API key header or different SOAP envelope format).")

    print("\n✅ Done!")
