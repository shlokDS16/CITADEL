import google.generativeai as genai
import time

API_KEY = "AIzaSyDSewl6MhI_g--eyjFOjORt3pjM43YcUZ4"
genai.configure(api_key=API_KEY)

models_to_try = [
    'gemini-1.5-flash',
    'gemini-1.5-pro',
    'gemini-flash-latest',
    'gemini-pro-latest'
]

for m_name in models_to_try:
    print(f"Trying {m_name}...")
    try:
        model = genai.GenerativeModel(m_name)
        response = model.generate_content("Hello")
        print(f"SUCCESS with {m_name}: {response.text}")
        break
    except Exception as e:
        print(f"FAILED with {m_name}: {e}")
        time.sleep(1)
