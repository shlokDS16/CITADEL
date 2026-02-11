
import asyncio
from services.llm_provider import llm_provider

async def test_gen():
    print("Testing generate...")
    try:
        res = await llm_provider.generate("Say 'Ollama is Working' in one sentence.")
        print("Result:", res)
    except Exception as e:
        print("Failed:", e)

if __name__ == "__main__":
    asyncio.run(test_gen())
