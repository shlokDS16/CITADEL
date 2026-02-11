import google.generativeai as genai
import os
from dotenv import load_dotenv

# Hardcode key for direct test to avoid env issues
API_KEY = "AIzaSyDSewl6MhI_g--eyjFOjORt3pjM43YcUZ4"

print(f"Using Key: {API_KEY[:5]}...{API_KEY[-5:]}")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-pro')

try:
    print("Sending request to Gemini...")
    response = model.generate_content("Hello, can you hear me?")
    print("Response received:")
    print(response.text)
except Exception as e:
    print("Error:")
    print(e)
