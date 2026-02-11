
import asyncio
from services.rag_service import retrieve_context

async def test():
    query = "fine for no helmet"
    docs, ids = await retrieve_context(query)
    print(f"Query: {query}")
    print(f"Results: {len(docs)}")
    for d in docs:
        print(f"Content: {d['chunk_text']}")
        print(f"Source: {d['metadata'].get('source')}")

if __name__ == "__main__":
    asyncio.run(test())
