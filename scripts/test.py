#!/usr/bin/env python3
"""
StudentVue SOAP API Test Script
District: Midland Public Schools (mi-mps.edupoint.com)

Test 1: No-auth ping — checks if the SOAP endpoint is alive
Test 2: District lookup — uses Edupoint's public credentials
Test 3: Auth template — username/password login to fetch gradebook
"""

import requests
import sys

BASE_HOST = "mi-mps.edupoint.com"
SOAP_ENDPOINT = f"https://{BASE_HOST}/Service/PXPCommunication.asmx"
HDINFO_ENDPOINT = f"https://{BASE_HOST}/Service/HDInfoCommunication.asmx"

HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": "http://edupoint.com/webservices/ProcessWebServiceRequest",
    "User-Agent": "StudentVUE/8.0.26 CFNetwork/1121.2.2 Darwin/19.3.0",
}


def build_soap_envelope(user_id, password, handle_name, method_name, param_str):
    """Build a SOAP envelope for ProcessWebServiceRequest."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ProcessWebServiceRequest xmlns="http://edupoint.com/webservices/">
      <userID>{user_id}</userID>
      <password>{password}</password>
      <skipLoginLog>1</skipLoginLog>
      <parent>0</parent>
      <webServiceHandleName>{handle_name}</webServiceHandleName>
      <methodName>{method_name}</methodName>
      <paramStr>{param_str}</paramStr>
    </ProcessWebServiceRequest>
  </soap:Body>
</soap:Envelope>"""


def test_endpoint_alive():
    """Test 1: Just GET the .asmx page to see if the endpoint exists."""
    print("=" * 60)
    print("TEST 1: Check if SOAP endpoint is alive")
    print(f"  URL: {SOAP_ENDPOINT}")
    print("=" * 60)
    try:
        r = requests.get(SOAP_ENDPOINT, timeout=10)
        print(f"  Status: {r.status_code}")
        print(f"  Content-Type: {r.headers.get('Content-Type', 'N/A')}")
        if r.status_code == 200:
            # Check if it looks like a WSDL/ASMX page
            if "ProcessWebServiceRequest" in r.text:
                print("  ✅ SOAP endpoint is ALIVE and lists ProcessWebServiceRequest!")
            else:
                print("  ⚠️  Got 200 but doesn't look like a SOAP service page")
                print(f"  First 500 chars: {r.text[:500]}")
        else:
            print(f"  ❌ Non-200 response")
            print(f"  First 500 chars: {r.text[:500]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()


def test_district_lookup():
    """Test 2: Use Edupoint's public creds to look up district info by zip."""
    print("=" * 60)
    print("TEST 2: District lookup (public Edupoint credentials)")
    print(f"  URL: {HDINFO_ENDPOINT}")
    print("  Using: EdupointDistrictInfo / Edup01nt")
    print("  Zip: 48640 (Midland, MI)")
    print("=" * 60)

    param_str = ("&lt;Parms&gt;"
                 "&lt;Key&gt;5E4B7859-B805-474B-A833-FDB15D205D40&lt;/Key&gt;"
                 "&lt;MatchToDistrictZipCode&gt;48640&lt;/MatchToDistrictZipCode&gt;"
                 "&lt;/Parms&gt;")

    body = build_soap_envelope(
        user_id="EdupointDistrictInfo",
        password="Edup01nt",
        handle_name="HDInfoServices",
        method_name="GetMatchingDistrictList",
        param_str=param_str,
    )

    try:
        r = requests.post(HDINFO_ENDPOINT, data=body, headers=HEADERS, timeout=15)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            if "DistrictList" in r.text or "DistrictInfo" in r.text:
                print("  ✅ Got district info back!")
            else:
                print("  ⚠️  Got 200 but response may not contain district data")
            print(f"\n  --- Response (first 2000 chars) ---")
            print(r.text[:2000])
        else:
            print(f"  ❌ Non-200: {r.status_code}")
            print(r.text[:1000])
    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()


def test_auth_login(username, password):
    """Test 3: Attempt to authenticate and fetch the gradebook."""
    print("=" * 60)
    print("TEST 3: Authenticated login — Gradebook request")
    print(f"  URL: {SOAP_ENDPOINT}")
    print(f"  User: {username}")
    print("=" * 60)

    # Try Gradebook method
    param_str = "&lt;Parms&gt;&lt;ChildIntID&gt;0&lt;/ChildIntID&gt;&lt;/Parms&gt;"

    body = build_soap_envelope(
        user_id=username,
        password=password,
        handle_name="PXPWebServices",
        method_name="Gradebook",
        param_str=param_str,
    )

    try:
        r = requests.post(SOAP_ENDPOINT, data=body, headers=HEADERS, timeout=15)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            if "Invalid" in r.text or "invalid" in r.text:
                print("  ❌ Auth likely failed (invalid credentials in response)")
            elif "Gradebook" in r.text or "Course" in r.text:
                print("  ✅ GOT GRADEBOOK DATA! Auth works!")
            else:
                print("  ⚠️  Got 200 — check response below for details")
            print(f"\n  --- Response (first 3000 chars) ---")
            print(r.text[:3000])
        else:
            print(f"  ❌ Non-200: {r.status_code}")
            print(r.text[:1000])
    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()


def test_student_info(username, password):
    """Test 3b: Try StudentInfo method as a simpler auth check."""
    print("=" * 60)
    print("TEST 3b: Authenticated login — StudentInfo request")
    print(f"  URL: {SOAP_ENDPOINT}")
    print("=" * 60)

    param_str = "&lt;Parms&gt;&lt;ChildIntID&gt;0&lt;/ChildIntID&gt;&lt;/Parms&gt;"

    body = build_soap_envelope(
        user_id=username,
        password=password,
        handle_name="PXPWebServices",
        method_name="StudentInfo",
        param_str=param_str,
    )

    try:
        r = requests.post(SOAP_ENDPOINT, data=body, headers=HEADERS, timeout=15)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            if "Invalid" in r.text or "invalid" in r.text:
                print("  ❌ Auth likely failed")
            elif "Student" in r.text:
                print("  ✅ Got student info! Auth works!")
            else:
                print("  ⚠️  Got 200 — check response")
            print(f"\n  --- Response (first 3000 chars) ---")
            print(r.text[:3000])
        else:
            print(f"  ❌ Non-200: {r.status_code}")
            print(r.text[:1000])
    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()


if __name__ == "__main__":
    print("\n🔍 StudentVue SOAP API Test — Midland Public Schools\n")

    # Always run connectivity tests
    test_endpoint_alive()
    test_district_lookup()

    # Auth tests only if credentials provided
    if len(sys.argv) == 3:
        username = sys.argv[1]
        password = sys.argv[2]
        test_auth_login(username, password)
        test_student_info(username, password)
    else:
        print("=" * 60)
        print("TEST 3: SKIPPED — No credentials provided")
        print("  To test auth, run:")
        print("    python3 test_studentvue.py YOUR_USERNAME YOUR_PASSWORD")
        print("=" * 60)

    print("\n✅ Done!")
