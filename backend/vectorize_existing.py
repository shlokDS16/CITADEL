
import asyncio
from supabase import create_client
from sentence_transformers import SentenceTransformer
from config import SUPABASE_URL, SUPABASE_KEY, EMBEDDING_MODEL

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
model = SentenceTransformer(EMBEDDING_MODEL)

async def vectorize_existing_docs():
    print("Fetching documents without embeddings...")
    docs = supabase.table("rag_documents").select("id, content").execute()
    
    for doc in docs.data:
        # Check if embedding already exists
        eb = supabase.table("rag_embeddings").select("id").eq("document_id", doc['id']).execute()
        if not eb.data:
            print(f"Vectorizing: {doc['id']}...")
            vector = model.encode(doc['content']).tolist()
            supabase.table("rag_embeddings").insert({
                "document_id": doc['id'],
                "content": doc['content'],
                "embedding": vector,
                "chunk_index": 0,
                "metadata": {"source": "manual_sync"}
            }).execute()
            print(f"Done.")
        else:
            print(f"Skipping: {doc['id']} (already exists)")

if __name__ == "__main__":
    asyncio.run(vectorize_existing_docs())
