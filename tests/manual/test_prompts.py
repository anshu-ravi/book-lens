"""Manual test script for proactive prompts."""

import os
import sys

# Ensure the parent dir is in PATH for src imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from src.main import app

def test_prompts():
    print("Testing /query/prompts endpoint...")
    client = TestClient(app)
    
    # Needs a library and a loaded epub to actually hit Anthropic correctly,
    # but we can try pinging the endpoint with a fake series to test 404 behavior.
    response = client.post("/query/prompts", json={
        "series_id": "fake_series",
        "book_index": 0,
        "chapter_index": 0
    })
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    if response.status_code == 404:
        print("Expected 404 received for fake series.")
    else:
        print("Unexpected behavior!")

if __name__ == "__main__":
    test_prompts()
