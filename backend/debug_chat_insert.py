import asyncio
import os
from datetime import datetime
from uuid import uuid4
from supabase import create_client
from dotenv import load_dotenv

# Load env from parent directory or current
load_dotenv() 

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mkhsdcxvwitndyfqtaqq.supabase.co")
# Need a key. I'll use the service key if available or anon key from config.py
# But config.py reads from env. I'll read config.py directly or copy values.
# Let's read config.py values manually for this test script.
# Actually I can import config.
import sys
sys.path.append('.')
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def test_insert():
    print(f"Testing insert to chat_sessions...")
    session_id = uuid4()
    user_id = "00000000-0000-0000-0000-000000000001"
    
    record = {
        "id": str(session_id),
        "user_id": user_id,
        "session_type": "rag",
        "messages": [],
        "context_documents": [],
        "created_at": datetime.utcnow().isoformat()
    }
    
    try:
        data = supabase.table("chat_sessions").insert(record).execute()
        print("Insert successful:", data)
    except Exception as e:
        print("Insert failed:")
        print(e)
        # If it's a postgrest error, it might have details
        if hasattr(e, 'message'):
            print("Message:", e.message)
        if hasattr(e, 'code'):
            print("Code:", e.code)
        if hasattr(e, 'details'):
            print("Details:", e.details)
        if hasattr(e, 'hint'):
            print("Hint:", e.hint)

if __name__ == "__main__":
    asyncio.run(test_insert())
