"""
Seed Government FAQ to RAG corpus
Quick script to add just the FAQ/policy data
"""
import json
import asyncio
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from sentence_transformers import SentenceTransformer
from supabase import create_client

# Configuration
SUPABASE_URL = "https://mkhsdcxvwitndyfqtaqq.supabase.co"
EMBEDDING_MODEL = "all-mpnet-base-v2"
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

DATA_DIR = Path(__file__).parent
FAQ_PATH = DATA_DIR / "government_faq.json"


def chunk_text(text: str, max_length: int = 500, overlap: int = 50):
    if len(text) <= max_length:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_length
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks


async def main():
    print("\n" + "="*60)
    print("  Government FAQ Seeder")
    print("="*60)
    
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    
    with open(FAQ_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    policy_count = 0
    scheme_count = 0
    vector_count = 0
    
    print("\n📋 Seeding Policies...")
    for policy in data.get("policies", []):
        try:
            doc_id = uuid4()
            content = f"Policy: {policy['title']}\nCategory: {policy['category']}\n\n{policy['content']}"
            
            doc_record = {
                "id": str(doc_id),
                "title": policy['title'],
                "doc_type": "policy",
                "source_tier": "government",
                "raw_text": content,
                "extracted_fields": {"category": policy['category']},
                "pii_detected": False,
                "status": "processed",
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("documents").insert(doc_record).execute()
            
            # Main content embedding
            embedding = embedder.encode(content).tolist()
            supabase.table("vectors").insert({
                "id": str(uuid4()),
                "embedding": embedding,
                "source_ref": str(doc_id),
                "source_type": "policy",
                "chunk_text": content[:1000],
                "metadata": {"title": policy['title'], "type": "policy"},
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            vector_count += 1
            
            # Add FAQs as separate vectors
            for faq in policy.get('faq', []):
                faq_text = f"Q: {faq['q']}\nA: {faq['a']}"
                faq_embedding = embedder.encode(faq_text).tolist()
                supabase.table("vectors").insert({
                    "id": str(uuid4()),
                    "embedding": faq_embedding,
                    "source_ref": str(doc_id),
                    "source_type": "faq",
                    "chunk_text": faq_text,
                    "metadata": {"policy": policy['title'], "question": faq['q']},
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                vector_count += 1
            
            policy_count += 1
            print(f"  ✓ {policy['title']} ({len(policy.get('faq',[]))} FAQs)")
            
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
    
    print("\n📋 Seeding Schemes...")
    for scheme in data.get("schemes", []):
        try:
            doc_id = uuid4()
            content = f"Government Scheme: {scheme['name']}\n\nDescription: {scheme['description']}\n\nEligibility: {scheme['eligibility']}\n\nBenefits: {scheme['benefits']}\n\nHow to Apply: {scheme['how_to_apply']}"
            
            doc_record = {
                "id": str(doc_id),
                "title": scheme['name'],
                "doc_type": "scheme",
                "source_tier": "government",
                "raw_text": content,
                "extracted_fields": {"eligibility": scheme['eligibility']},
                "pii_detected": False,
                "status": "processed",
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("documents").insert(doc_record).execute()
            
            embedding = embedder.encode(content).tolist()
            supabase.table("vectors").insert({
                "id": str(uuid4()),
                "embedding": embedding,
                "source_ref": str(doc_id),
                "source_type": "scheme",
                "chunk_text": content,
                "metadata": {"scheme_name": scheme['name']},
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            vector_count += 1
            
            scheme_count += 1
            print(f"  ✓ {scheme['name']}")
            
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
    
    # Final count
    result = supabase.table("vectors").select("id", count="exact").execute()
    
    print("\n" + "="*60)
    print(f"  ✅ Seeded {policy_count} policies, {scheme_count} schemes")
    print(f"  📊 Total vectors in DB: {result.count}")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
