
import asyncio
from services.rag_service import chat, create_chat_session
from uuid import uuid4

async def test_full_chat():
    user_id = uuid4()
    
    # Create session first
    session_id = await create_chat_session(user_id)
    print(f"Created session: {session_id}")
    
    # query = "What is the fine for not wearing a helmet?"
    query = "How to improve traffic safety in the city?"
    print(f"Testing chat for: {query}")
    
    response = await chat(session_id, user_id, query)
    
    print(f"Response: {response['answer']}")
    print(f"Confidence: {response['confidence']}")
    print(f"Sources: {len(response['sources'])}")

if __name__ == "__main__":
    asyncio.run(test_full_chat())
