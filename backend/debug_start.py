
print("Importing main...")
import main
print("Main imported.")
print("Starting uvicorn...")
import uvicorn
uvicorn.run(main.app, host="0.0.0.0", port=8000)
