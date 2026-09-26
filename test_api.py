import urllib.request
import json
import time
import os

try:
    from backend.config import settings
    API_KEY = os.environ.get("NIKOLA_API_KEY", settings.NIKOLA_API_KEY)
except Exception:
    API_KEY = os.environ.get("NIKOLA_API_KEY", "nikola-dev-key-change-in-production")

def test_endpoint(name, url, method="GET", data=None):
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header('X-API-Key', API_KEY)
        if data:
            req.add_header('Content-Type', 'application/json')
            data = json.dumps(data).encode('utf-8')
            
        start = time.time()
        with urllib.request.urlopen(req, data=data, timeout=10) as response:
            result = json.loads(response.read().decode())
            elapsed = time.time() - start
            print(f"[PASS] [{name}] ({elapsed:.2f}s)")
            print(f"   Response: {str(result)[:200]}...")
            return True
            
    except Exception as e:
        print(f"[FAIL] [{name}]")
        print(f"   Error: {str(e)}")
        return False

if __name__ == "__main__":
    print("\n--- Testing NIKOLA API Health ---")
    
    # 1. Test basic health
    test_endpoint("Health Check", "http://localhost:8000/health")
    
    # 2. Test status endpoint
    test_endpoint("System Status", "http://localhost:8000/status")
    
    # 3. Test retrieving autofill fields
    test_endpoint("Autofill Profile", "http://localhost:8000/autofill/profile")
    
    # 4. Test RAG files listing
    test_endpoint("RAG Files List", "http://localhost:8000/rag/files")
    
    # 5. Test LLM directly (Ask without RAG)
    test_endpoint(
        "LLM Inference (Ask)", 
        "http://localhost:8000/ask", 
        method="POST", 
        data={"query": "Hello! Reply with 'Nikola is ready!'", "use_rag": False}
    )
    
    print("\n--- Test Complete ---")
