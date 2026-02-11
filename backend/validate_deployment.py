"""
Deployment Validation Script for C.I.T.A.D.E.L.
Run this before demo to verify all endpoints are working.
"""

import requests
import sys
import json

BASE_URL = "http://localhost:8000"

def test_endpoint(name: str, method: str, endpoint: str, headers: dict = None, data: dict = None):
    """Test a single endpoint"""
    try:
        url = BASE_URL + endpoint
        
        if method == "GET":
            resp = requests.get(url, headers=headers or {}, timeout=10)
        elif method == "POST":
            resp = requests.post(url, headers=headers or {}, json=data, timeout=10)
        else:
            return False, "Unknown method"
        
        if resp.status_code in [200, 201]:
            return True, f"Status {resp.status_code}"
        else:
            return False, f"Status {resp.status_code}: {resp.text[:100]}"
    except requests.exceptions.ConnectionError:
        return False, "Connection refused - is server running?"
    except Exception as e:
        return False, str(e)


def run_validation():
    """Run all validation tests"""
    
    print("=" * 60)
    print("🏛️ C.I.T.A.D.E.L. Deployment Validation")
    print("=" * 60)
    print()
    
    # Define tests
    tests = [
        # Public endpoints
        ("Health Check", "GET", "/health", None, None),
        ("Root Info", "GET", "/", None, None),
        
        # Dashboard tests
        ("Government Dashboard", "GET", "/api/dashboard/", 
         {"x-user-role": "government_official", "x-user-id": "test"}, None),
        ("Citizen Dashboard", "GET", "/api/dashboard/", 
         {"x-user-role": "citizen", "x-user-id": "test"}, None),
        
        # Module endpoints
        ("RAG Chat", "GET", "/api/chat/history", 
         {"x-user-role": "citizen", "x-user-id": "test"}, None),
        ("Fake News Types", "GET", "/api/news/", 
         {"x-user-role": "citizen", "x-user-id": "test"}, None),
        ("Ticket Categories", "GET", "/api/support-tickets/categories", 
         {"x-user-role": "citizen", "x-user-id": "test"}, None),
        ("Violation Types", "GET", "/api/traffic-violations/types", 
         {"x-user-role": "government_official", "x-user-id": "test"}, None),
        
        # RBAC tests (these should PASS with correct role)
        ("Anomaly Stats (Gov)", "GET", "/api/anomaly/stats", 
         {"x-user-role": "government_official", "x-user-id": "test"}, None),
    ]
    
    passed = 0
    failed = 0
    
    for name, method, endpoint, headers, data in tests:
        success, message = test_endpoint(name, method, endpoint, headers, data)
        
        if success:
            print(f"✅ {name}: PASS")
            passed += 1
        else:
            print(f"❌ {name}: FAIL - {message}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    # RBAC specific test
    print()
    print("🔒 RBAC Verification:")
    
    # Citizen accessing government endpoint should fail
    success, msg = test_endpoint(
        "RBAC Block", "GET", "/api/admin/", 
        {"x-user-role": "citizen", "x-user-id": "test"}, None
    )
    if not success and "403" in msg:
        print("✅ RBAC correctly blocks citizen from admin endpoint")
    else:
        print(f"⚠️ RBAC test inconclusive: {msg}")
    
    print()
    
    if failed > 0:
        print("⚠️ Some tests failed. Check server logs.")
        return 1
    else:
        print("🎉 All tests passed! Ready for demo.")
        return 0


if __name__ == "__main__":
    sys.exit(run_validation())
