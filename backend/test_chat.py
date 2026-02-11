import requests
import json

def test_chat():
    url = "http://localhost:8000/api/chat/"
    payload = {"message": "How do I apply for a driver license?"}
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            print("Status: 200 OK")
            print("Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Status: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_chat()
