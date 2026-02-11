import google.generativeai as genai

API_KEY = "AIzaSyDSewl6MhI_g--eyjFOjORt3pjM43YcUZ4"
genai.configure(api_key=API_KEY)

try:
    print("Listing models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print("Error listing models:", e)
