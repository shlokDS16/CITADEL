import google.generativeai as genai

API_KEY = "AIzaSyDSewl6MhI_g--eyjFOjORt3pjM43YcUZ4"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

try:
    print("Sending request to Gemini 2.0 Flash...")
    response = model.generate_content("Hello")
    print("Response received:")
    print(response.text)
except Exception as e:
    print("Error:")
    print(e)
