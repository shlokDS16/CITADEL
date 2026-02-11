
import requests
import json
import time

URL = "http://localhost:8000/api/chat"
SESSION_URL = "http://localhost:8000/api/chat/session"

def test_chat():
    try:
        # Create session
        print("Creating session...")
        res = requests.post(SESSION_URL)
        if res.status_code != 200:
            print(f"Failed to create session: {res.text}")
            return
            
        session_id = res.json()["session_id"]
        print(f"Session ID: {session_id}")
        
        # Send message
        msg = "Who is the Prime Minister of India?"
        print(f"\nSending message: '{msg}'")
        
        start = time.time()
        res = requests.post(URL, json={"message": msg, "session_id": session_id})
        duration = time.time() - start
        
        if res.status_code == 200:
            data = res.json()
            print(f"\n✅ Response received in {duration:.1f}s:")
            print(f"Answer: {data.get('answer')}")
            print(f"Sources: {len(data.get('sources', []))}")
            if "I apologize" in data.get('answer', ''):
                print("❌ WARNING: Received default error response.")
            else:
                print("✅ Success! Chatbot is answering.")
        else:
            print(f"❌ API Error {res.status_code}: {res.text}")
            
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("Make sure backend is running on port 8000")

if __name__ == "__main__":
    test_chat()
