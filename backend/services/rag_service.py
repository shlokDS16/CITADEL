"""
RAG Service - Retrieval Augmented Generation for Citizen Chatbot
- Vector similarity search
- Context-aware answer generation
- Citation tracking
"""
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from datetime import datetime
import google.generativeai as genai
import time

from supabase import create_client
from sentence_transformers import SentenceTransformer

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    EMBEDDING_MODEL, LLM_MODEL, GOOGLE_API_KEY,
    CHAT_SESSION_MAX_MESSAGES
)
from services.audit_service import log_ai_decision

from services.llm_provider import llm_provider

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
embedding_model = SentenceTransformer(EMBEDDING_MODEL)

async def create_chat_session(user_id: UUID, session_type: str = "rag") -> UUID:
    """Create a new chat session"""
    session_id = uuid4()
    
    record = {
        "id": str(session_id),
        "user_id": str(user_id),
        "session_type": session_type,
        "messages": [],
        "context_documents": [],
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("chat_sessions").insert(record).execute()
    return session_id


async def chat(
    session_id: UUID,
    user_id: UUID,
    message: str,
    session_type: str = "rag"
) -> Dict[str, Any]:
    """
    Process a chat message and generate response with citations.
    Returns answer with sources and confidence.
    """
    # Check session message limit
    session = await get_session(session_id)
    if session and len(session.get("messages", [])) >= CHAT_SESSION_MAX_MESSAGES:
        return {
            "error": "Session limit reached",
            "max_messages": CHAT_SESSION_MAX_MESSAGES
        }
    
    # Step 1: Retrieve relevant documents
    retrieved_docs, vector_ids = await retrieve_context(message)
    
    # Step 2: Generate answer with context
    answer, confidence, sources = await generate_answer(message, retrieved_docs)
    
    # Step 3: Store message in session
    await append_message(session_id, "user", message)
    await append_message(session_id, "assistant", answer, sources)
    
    # Step 4: Update context documents in session
    doc_ids = list(set(doc["doc_id"] for doc in retrieved_docs if doc.get("doc_id")))
    await update_session_context(session_id, doc_ids, vector_ids)
    
    # Step 5: Log AI decision
    decision_id = await log_ai_decision(
        model_name=LLM_MODEL,
        model_version="1.0.0",
        module="rag",
        input_data={"query": message, "session_id": str(session_id)},
        output={"answer": answer[:500], "sources_count": len(sources)},
        confidence=confidence,
        vector_ids=[UUID(v) for v in vector_ids] if vector_ids else None,
        evidence=[{"type": "retrieved_chunk", "content": doc["chunk_text"][:200]} for doc in retrieved_docs[:3]],
        explanation=f"Generated answer from {len(retrieved_docs)} retrieved chunks"
    )
    
    return {
        "answer": answer,
        "confidence": confidence,
        "sources": sources,
        "decision_id": str(decision_id),
        "session_id": str(session_id)
    }


async def retrieve_context(query: str, top_k: int = 5) -> tuple[List[Dict], List[str]]:
    """
    Retrieve relevant document chunks using vector similarity and keyword context.
    Returns (documents, vector_ids)
    """
    # Generate query embedding
    query_embedding = embedding_model.encode(query).tolist()
    
    # Step 1: Live Keyword Search on Official Fines/Policies (THE SOURCE OF TRUTH)
    # This ensures any direct update in Supabase (e.g. helmet fine = 30) is reflected INSTANTLY
    try:
        import re
        clean_query = re.sub(r'[^\w\s]', '', query.lower())
        words = set(clean_query.split())
        
        # Filter and prioritize keywords
        ignored_words = {'what', 'fine', 'fines', 'wearing', 'riding', 'using', 'gives', 'tell', 'show', 'please'}
        keywords = [w for w in words if len(w) > 3 and w not in ignored_words]
        
        # If no keywords left after filtering, use all words len > 3
        if not keywords:
            keywords = [w for w in words if len(w) > 3]
            
        # Sort by length descending
        keywords.sort(key=len, reverse=True)
        
        all_fine_results = []
        seen_ids = set()
        
        for kw in keywords[:3]: # check top 3 keywords
            fines = supabase.table("govt_fines_penalties").select("*") \
                .or_(f"violation_type.ilike.%{kw}%,description.ilike.%{kw}%") \
                .execute()
                
            if fines.data:
                for f in fines.data:
                    if f['id'] not in seen_ids:
                        text = f"OFFICIAL GOVT RECORD: Violation '{f['violation_type']}' carries a fine of ₹{f['fine_amount']}. Details: {f['description']}."
                        print(f"SYNC_STATUS: Real-time fine '{f['violation_type']}' (₹{f['fine_amount']}) retrieved from Supabase.")
                        all_fine_results.append({
                            "id": f["id"],
                            "chunk_text": text,
                            "similarity": 1.0,
                            "metadata": {"source": "live_fines", "violation": f['violation_type']}
                        })
                        seen_ids.add(f['id'])
        
        if all_fine_results:
            return all_fine_results, list(seen_ids)
            
    except Exception as e:
        print(f"Live keyword search failed: {e}")

    # Step 2: Perform vector similarity search for knowledge base
    # (Fallback/Context for non-fine related queries)
    try:
        query_embedding = embedding_model.encode(query).tolist()
        results = supabase.rpc(
            'match_rag_documents',
            {
                'query_embedding': query_embedding,
                'match_threshold': 0.35,
                'match_count': top_k
            }
        ).execute()
        
        if results.data:
            formatted_results = []
            vector_ids = []
            for r in results.data:
                formatted_results.append({
                    "id": r["id"],
                    "chunk_text": r["content"],
                    "similarity": r["similarity"],
                    "metadata": r.get("metadata", {})
                })
                vector_ids.append(str(r["id"]))
            return formatted_results, vector_ids
            
    except Exception as e:
        print(f"Vector search failed: {e}")
        pass
    
    # Fallback: simple text search (if vector search fails or returns nothing)
    try:
        results = supabase.table("vectors").select("*").textSearch(
            "chunk_text", query, config="english"
        ).limit(top_k).execute()
        
        if results.data:
            vector_ids = [r["id"] for r in results.data]
            return results.data, vector_ids
    except Exception:
        pass

    return [], []


async def generate_answer(
    query: str,
    context_docs: List[Dict]
) -> tuple[str, float, List[Dict]]:
    """
    Generate answer using retrieved context via LLMProvider (Ollama).
    Returns (answer, confidence, sources)
    """
    # Build context string
    context_parts = []
    sources = []
    
    for i, doc in enumerate(context_docs):
        # Handle 'chunk_text' returned by RPC or Table
        content = doc.get('chunk_text', '')
        context_parts.append(f"[Source {i+1}]: {content}")
        sources.append({
            "source_id": doc.get("id"),
            "doc_id": doc.get("doc_id"),
            "excerpt": content[:200],
            "relevance": doc.get("similarity", 0.8)
        })
    
    context = "\n\n".join(context_parts)
    
    # Generate answer using LLM
    try:
        # If no relevant context found (context empty), use general knowledge
        if not context:
             answer = await call_llm_no_context(query)
             confidence = 0.5 
             
             # LEARNING LOOP: Store this new knowledge back into the RAG database
             # This will trigger the global sync across all modules
             await ingest_learned_knowledge(query, answer)
        else:
            answer = await call_llm(query, context)
            confidence = 0.8 # Assume higher confidence if context was used
    except Exception as e:
        # Fallback: Error message
        print(f"LLM generation failed: {e}")
        answer = "I apologize, but I'm currently experiencing technical difficulties. " + str(e)
        confidence = 0.0
    
    return answer, confidence, sources


async def ingest_learned_knowledge(query: str, answer: str):
    """
    Self-learning logic: Ingest Ollama's response into RAG database.
    This automatically triggers the Context Engine broadcast.
    """
    try:
        # 1. Store in rag_documents (triggers SQL logic to broadcast to all modules)
        title = query[:50] + "..." if len(query) > 50 else query
        
        doc_record = {
            "title": f"Learned: {title}",
            "content": f"Query: {query}\n\nAnswer: {answer}",
            "document_type": "learned_knowledge",
            "source_module": "rag_chatbot"
        }
        
        result = supabase.table("rag_documents").insert(doc_record).execute()
        
        if result.data:
            doc_id = result.data[0]["id"]
            
            # 2. Generate embedding for the new knowledge
            # This ensures it's searchable in the next query
            embedding = embedding_model.encode(answer).tolist()
            
            supabase.table("rag_embeddings").insert({
                "document_id": doc_id,
                "content": answer,
                "embedding": embedding,
                "chunk_index": 0,
                "metadata": {"source": "ollama_learning", "original_query": query}
            }).execute()
            
            print(f"KNOWLEDGE ACQUIRED: '{title}' synchronized to all modules.")
            
    except Exception as e:
        print(f"Learning loop failed: {e}")


async def call_llm(query: str, context: str) -> str:
    """Call LLMProvider for answer generation with context (Hybrid)"""
    
    system_instruction = "You are CITADEL, an advanced AI assistant for the government. You are helpful, professional, and accurate."
    
    prompt = f"""Context from Government Database:
{context}

User Question: {query}

Instructions:
1. PRIORITIZE information from the provided Context.
2. If the Context contains the answer, use it and cite source numbers like [Source 1].
3. If the Context DOES NOT contain the answer, you MAY answer using your internal general knowledge.
4. If answering from general knowledge, do NOT make up specific government policies or fine amounts.
5. Be concise and direct.

Answer:"""
    
    try:
        return await llm_provider.generate(prompt, system_instruction)
    except Exception as e:
        print(f"LLM Provider Error: {e}")
        raise e

async def call_llm_no_context(query: str) -> str:
    """Call LLMProvider for general questions (No docs found)"""
    
    system_instruction = "You are CITADEL, a helpful government AI chatbot."
    
    prompt = f"""User Question: "{query}"

System Note: No specific government documents were found for this query in the vector database.

Instructions:
1. Answer the user's question helpfully using your general knowledge.
2. If the question is about specific local laws, fines, or official procedures that vary by city, advise the user to check the official portal or contact support.
3. If it is a general question (e.g., "What is AI?", "Who are you?", "How to save water?"), answer it fully.
4. Keep the tone professional and helpful.

Answer:"""
    
    try:
        return await llm_provider.generate(prompt, system_instruction)
    except Exception as e:
        return "I am here to help, but I'm having trouble processing your request right now."



async def get_session(session_id: UUID) -> Optional[Dict]:
    """Get chat session by ID"""
    result = supabase.table("chat_sessions").select("*").eq("id", str(session_id)).single().execute()
    return result.data


async def append_message(
    session_id: UUID,
    role: str,
    content: str,
    sources: Optional[List] = None
) -> None:
    """Append message to chat session"""
    session = await get_session(session_id)
    if not session:
        return
    
    messages = session.get("messages", [])
    messages.append({
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat(),
        "sources": [s["source_id"] for s in sources] if sources else []
    })
    
    supabase.table("chat_sessions").update({
        "messages": messages,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", str(session_id)).execute()


async def update_session_context(
    session_id: UUID,
    doc_ids: List[str],
    vector_ids: List[str]
) -> None:
    """Update session with context references"""
    supabase.table("chat_sessions").update({
        "context_documents": doc_ids,
        "vector_index_refs": vector_ids,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("id", str(session_id)).execute()


async def get_chat_history(session_id: UUID) -> List[Dict]:
    """Get chat history for a session"""
    session = await get_session(session_id)
    return session.get("messages", []) if session else []
