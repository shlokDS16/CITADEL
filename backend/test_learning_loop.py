
import asyncio
from services.rag_service import chat
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from uuid import uuid4

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def test_learning_loop():
    user_id = uuid4()
    session_id = uuid4()
    
    # Create session
    supabase.table("chat_sessions").insert({
        "id": str(session_id),
        "user_id": str(user_id),
        "session_type": "rag",
        "messages": []
    }).execute()

    # Query that isn't in RAG but Ollama knows
    query = "List three key benefits of decentralized government for local citizens."
    
    print(f"Querying: {query}")
    try:
        response = await chat(session_id, user_id, query)
        print(f"\nAnswer: {response['answer'][:100]}...")
    except Exception as e:
        print(f"Chat failed: {e}")
        return
    
    # Wait a bit for triggers
    print("Waiting for background sync...")
    await asyncio.sleep(5)
    
    # Check if knowledge was stored
    print("\nVerifying Database State:")
    
    # 1. Check rag_documents
    docs = supabase.table("rag_documents").select("*").ilike("title", "%Learned%").execute()
    print(f"Total Learned Docs in DB: {len(docs.data)}")
    for doc in docs.data:
        print(f" - Found Doc: {doc['title']}")
    
    # 2. Check context_entities
    entities = supabase.table("context_entities").select("*").eq("entity_type", "knowledge").execute()
    print(f"Total Knowledge Entities in DB: {len(entities.data)}")
    
    # 3. Check module sync
    syncs = supabase.table("module_context_state").select("*").ilike("context_key", "knowledge.%").execute()
    print(f"Total Module State Syncs: {len(syncs.data)}")
    
    # Check if specific modules (e.g. traffic_detection) got the knowledge
    traffic_sync = [s for s in syncs.data if s['module_name'] == 'traffic_detection']
    if traffic_sync:
        print("SUCCESS: traffic_detection is now aware of this new knowledge.")
    else:
        print("FAILURE: traffic_detection NOT synced.")

if __name__ == "__main__":
    asyncio.run(test_learning_loop())
