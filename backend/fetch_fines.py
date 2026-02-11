
import asyncio
from services.rag_service import supabase

async def get_fines():
    response = supabase.table("govt_fines_penalties").select("*").execute()
    for row in response.data:
        print(f"Violation: {row['violation_type']}, Fine: {row['fine_amount']}")

if __name__ == "__main__":
    asyncio.run(get_fines())
