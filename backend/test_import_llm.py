
try:
    print("Importing llm_provider...")
    from services.llm_provider import llm_provider
    print("Success importing llm_provider")
except Exception as e:
    print(f"Failed importing llm_provider: {e}")

try:
    print("Importing rag_service...")
    from services.rag_service import chat
    print("Success importing rag_service")
except Exception as e:
    print(f"Failed importing rag_service: {e}")
