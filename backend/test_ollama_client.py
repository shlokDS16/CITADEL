
from ollama import Client

try:
    client = Client(host='http://localhost:11434')
    response = client.chat(model='llama3.2', messages=[
        {'role': 'user', 'content': 'Hello'}
    ])
    print("Response type:", type(response))
    print("Response content:", response)
    if isinstance(response, dict):
        print("Content:", response['message']['content'])
    else:
        print("Content (obj):", response.message.content)
except Exception as e:
    print("Error:", e)
