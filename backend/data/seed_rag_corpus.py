"""
RAG Corpus Seeder
Populates the vector database with comprehensive data from:
1. FUNSD forms (document understanding)
2. Government FAQ/Policy documents
3. Government schemes information
"""
import json
import asyncio
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from typing import List, Dict

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sentence_transformers import SentenceTransformer
from supabase import create_client

# Configuration
SUPABASE_URL = "https://mkhsdcxvwitndyfqtaqq.supabase.co"
EMBEDDING_MODEL = "all-mpnet-base-v2"

# Get key from environment
import os
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Paths
DATA_DIR = Path(__file__).parent
FUNSD_PATH = DATA_DIR / "dataset"
FAQ_PATH = DATA_DIR / "government_faq.json"


def chunk_text(text: str, max_length: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks for better retrieval"""
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


async def seed_funsd_documents(supabase, embedder, max_docs: int = 30):
    """Seed FUNSD form documents into vector DB"""
    print("\n📄 Seeding FUNSD Documents...")
    
    # Import FUNSD loader
    from loaders.funsd_loader import FUNSDLoader, extract_key_value_pairs
    
    loader = FUNSDLoader(str(FUNSD_PATH))
    count = 0
    
    for doc in loader.load_all():
        if count >= max_docs:
            break
        
        try:
            # Get document text
            full_text = doc.full_text
            kv_pairs = extract_key_value_pairs(doc)
            
            # Create document record
            doc_id = uuid4()
            doc_record = {
                "id": str(doc_id),
                "uploader_id": "00000000-0000-0000-0000-000000000001",
                "title": f"Form {doc.doc_id}",
                "doc_type": "form",
                "source_tier": "funsd",
                "raw_text": full_text,
                "extracted_fields": {
                    "key_value_pairs": kv_pairs,
                    "headers": [h.text for h in doc.headers]
                },
                "pii_detected": False,
                "status": "processed",
                "created_by": "00000000-0000-0000-0000-000000000001",
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("documents").insert(doc_record).execute()
            
            # Create embedding and vector entry
            embedding = embedder.encode(full_text[:2000]).tolist()
            vector_id = uuid4()
            supabase.table("vectors").insert({
                "id": str(vector_id),
                "embedding": embedding,
                "source_ref": str(doc_id),
                "source_type": "document",
                "chunk_text": full_text[:1000],
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            count += 1
            if count % 10 == 0:
                print(f"  Processed {count} documents...")
                
        except Exception as e:
            print(f"  ⚠️ Error processing {doc.doc_id}: {e}")
            continue
    
    print(f"  ✓ Seeded {count} FUNSD documents")
    return count


async def seed_government_faq(supabase, embedder):
    """Seed government FAQ and policy documents"""
    print("\n📋 Seeding Government FAQ & Policies...")
    
    with open(FAQ_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    policy_count = 0
    scheme_count = 0
    faq_count = 0
    
    # Process policies
    for policy in data.get("policies", []):
        try:
            doc_id = uuid4()
            
            # Create rich content for embedding
            content = f"""
Policy: {policy['title']}
Category: {policy['category']}

{policy['content']}

Frequently Asked Questions:
"""
            for faq in policy.get('faq', []):
                content += f"\nQ: {faq['q']}\nA: {faq['a']}\n"
            
            # Store document
            doc_record = {
                "id": str(doc_id),
                "uploader_id": "00000000-0000-0000-0000-000000000001",
                "title": policy['title'],
                "doc_type": "policy",
                "source_tier": "government",
                "raw_text": content,
                "extracted_fields": {
                    "category": policy['category'],
                    "faq_count": len(policy.get('faq', []))
                },
                "pii_detected": False,
                "status": "processed",
                "created_by": "00000000-0000-0000-0000-000000000001",
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("documents").insert(doc_record).execute()
            
            # Create chunks for better retrieval
            chunks = chunk_text(content, max_length=500)
            for i, chunk in enumerate(chunks):
                embedding = embedder.encode(chunk).tolist()
                vector_id = uuid4()
                supabase.table("vectors").insert({
                    "id": str(vector_id),
                    "embedding": embedding,
                    "source_ref": str(doc_id),
                    "source_type": "policy",
                    "chunk_text": chunk,
                    "metadata": {"chunk_index": i, "title": policy['title']},
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
            
            # Also store individual FAQs for precise matching
            for faq in policy.get('faq', []):
                faq_text = f"Q: {faq['q']}\nA: {faq['a']}"
                faq_embedding = embedder.encode(faq_text).tolist()
                faq_vector_id = uuid4()
                supabase.table("vectors").insert({
                    "id": str(faq_vector_id),
                    "embedding": faq_embedding,
                    "source_ref": str(doc_id),
                    "source_type": "faq",
                    "chunk_text": faq_text,
                    "metadata": {"policy": policy['title'], "question": faq['q']},
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                faq_count += 1
            
            policy_count += 1
            print(f"  ✓ {policy['title']}")
            
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
    
    # Process schemes
    for scheme in data.get("schemes", []):
        try:
            doc_id = uuid4()
            
            content = f"""
Government Scheme: {scheme['name']}

Description: {scheme['description']}

Eligibility: {scheme['eligibility']}

Benefits: {scheme['benefits']}

How to Apply: {scheme['how_to_apply']}
"""
            
            doc_record = {
                "id": str(doc_id),
                "uploader_id": "00000000-0000-0000-0000-000000000001",
                "title": scheme['name'],
                "doc_type": "scheme",
                "source_tier": "government",
                "raw_text": content,
                "extracted_fields": {
                    "eligibility": scheme['eligibility'],
                    "benefits": scheme['benefits']
                },
                "pii_detected": False,
                "status": "processed",
                "created_by": "00000000-0000-0000-0000-000000000001",
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("documents").insert(doc_record).execute()
            
            # Create embedding
            embedding = embedder.encode(content).tolist()
            vector_id = uuid4()
            supabase.table("vectors").insert({
                "id": str(vector_id),
                "embedding": embedding,
                "source_ref": str(doc_id),
                "source_type": "scheme",
                "chunk_text": content,
                "metadata": {"scheme_name": scheme['name']},
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            scheme_count += 1
            print(f"  ✓ {scheme['name']}")
            
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
    
    print(f"\n  ✓ Seeded {policy_count} policies, {scheme_count} schemes, {faq_count} FAQs")
    return policy_count + scheme_count


async def main():
    print("\n" + "="*60)
    print("  C.I.T.A.D.E.L. RAG Corpus Seeder")
    print("="*60)
    
    if not SUPABASE_KEY:
        print("\n⚠️  SUPABASE_KEY environment variable not set!")
        print("   Set it with: $env:SUPABASE_KEY='your_key'")
        print("   Or run with: SUPABASE_KEY=xxx python seed_rag_corpus.py")
        return
    
    print("\n📦 Initializing...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    print(f"   Model: {EMBEDDING_MODEL}")
    
    # Seed FUNSD
    funsd_count = await seed_funsd_documents(supabase, embedder, max_docs=30)
    
    # Seed Government FAQ
    faq_count = await seed_government_faq(supabase, embedder)
    
    # Summary
    print("\n" + "="*60)
    print("  ✅ RAG Corpus Seeding Complete!")
    print("="*60)
    print(f"\n  Documents: {funsd_count} forms + {faq_count} policies/schemes")
    
    # Verify counts
    result = supabase.table("vectors").select("id", count="exact").execute()
    print(f"  Vector DB entries: {result.count}")
    print("\n  Ready for RAG chatbot queries!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
