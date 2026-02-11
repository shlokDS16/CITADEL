"""
FUNSD Integration with Document Intelligence Service
Seeds the database with FUNSD documents for demo/testing.
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from funsd_loader import FUNSDLoader, FormDocument, extract_key_value_pairs
from PIL import Image
import io


async def seed_funsd_to_supabase(
    dataset_path: str,
    max_docs: int = 50,
    split: str = "training"
):
    """
    Seed FUNSD documents into Supabase for Document Intelligence demo.
    
    Args:
        dataset_path: Path to FUNSD dataset
        max_docs: Maximum documents to seed (to avoid overwhelming demo DB)
        split: 'training', 'testing', or 'all'
    """
    from supabase import create_client
    from sentence_transformers import SentenceTransformer
    from datetime import datetime
    
    # Import config
    try:
        from config import SUPABASE_URL, SUPABASE_KEY, EMBEDDING_MODEL
    except ImportError:
        print("⚠️  Config not found. Using environment variables.")
        import os
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        EMBEDDING_MODEL = "all-mpnet-base-v2"
    
    print(f"\n{'='*60}")
    print("  FUNSD → Supabase Seeder")
    print(f"{'='*60}\n")
    
    # Initialize
    print("📦 Loading models...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    loader = FUNSDLoader(dataset_path)
    
    # Select split
    if split == "training":
        docs = loader.load_training()
    elif split == "testing":
        docs = loader.load_testing()
    else:
        docs = loader.load_all()
    
    print(f"📄 Processing {split} documents (max {max_docs})...\n")
    
    count = 0
    for doc in docs:
        if count >= max_docs:
            break
        
        try:
            # Extract text and key-value pairs
            full_text = doc.full_text
            kv_pairs = extract_key_value_pairs(doc)
            
            # Generate embedding
            embedding = embedder.encode(full_text[:2000]).tolist()
            
            # Create document record
            doc_id = uuid4()
            doc_record = {
                "id": str(doc_id),
                "uploader_id": "00000000-0000-0000-0000-000000000001",
                "title": f"FUNSD Form {doc.doc_id}",
                "doc_type": "form",
                "source_tier": "funsd_training" if split == "training" else "funsd_testing",
                "raw_text": full_text,
                "extracted_fields": {
                    "headers": [h.text for h in doc.headers],
                    "questions": [q.text for q in doc.questions],
                    "answers": [a.text for a in doc.answers],
                    "key_value_pairs": kv_pairs
                },
                "pii_detected": False,
                "status": "processed",
                "created_by": "00000000-0000-0000-0000-000000000001",
                "created_at": datetime.utcnow().isoformat()
            }
            
            # Insert document
            supabase.table("documents").insert(doc_record).execute()
            
            # Store embedding
            vector_id = uuid4()
            supabase.table("vectors").insert({
                "id": str(vector_id),
                "embedding": embedding,
                "source_ref": str(doc_id),
                "source_type": "document",
                "chunk_text": full_text[:1000],
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            # Store extracted fields
            for kv in kv_pairs:
                field_id = uuid4()
                supabase.table("extracted_fields").insert({
                    "id": str(field_id),
                    "document_id": str(doc_id),
                    "field_name": kv["question"],
                    "field_value": kv["answer"],
                    "confidence": 0.95,  # Ground truth from dataset
                    "bounding_box": {
                        "question": kv["question_box"],
                        "answer": kv["answer_box"]
                    },
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
            
            count += 1
            print(f"  ✓ [{count}/{max_docs}] {doc.doc_id} - {len(kv_pairs)} fields")
            
        except Exception as e:
            print(f"  ✗ {doc.doc_id} - Error: {e}")
            continue
    
    print(f"\n{'='*60}")
    print(f"  ✅ Seeded {count} documents to Supabase")
    print(f"{'='*60}\n")
    
    return count


def export_for_inference(
    dataset_path: str,
    output_path: str,
    max_docs: int = 100
):
    """
    Export FUNSD data in a format ready for our Document Intelligence inference.
    Creates JSON files that can be used for testing.
    """
    import json
    
    print(f"\n{'='*60}")
    print("  FUNSD → Inference Format Export")
    print(f"{'='*60}\n")
    
    loader = FUNSDLoader(dataset_path)
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    documents = []
    
    for count, doc in enumerate(loader.load_all()):
        if count >= max_docs:
            break
        
        kv_pairs = extract_key_value_pairs(doc)
        
        doc_data = {
            "id": doc.doc_id,
            "image_path": str(doc.image_path),
            "text": doc.full_text,
            "fields": kv_pairs,
            "headers": [h.text for h in doc.headers],
            "field_count": len(doc.fields),
            "qa_pair_count": len(kv_pairs)
        }
        documents.append(doc_data)
        print(f"  ✓ Exported {doc.doc_id}")
    
    # Save to JSON
    output_file = output_dir / "funsd_inference_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)
    
    print(f"\n  📁 Saved to: {output_file}")
    print(f"  📊 Total documents: {len(documents)}")
    print(f"{'='*60}\n")
    
    return len(documents)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="FUNSD Integration")
    parser.add_argument("--action", choices=["seed", "export"], default="export")
    parser.add_argument("--dataset", default=r"c:\Users\shlok\Downloads\Hackathon-2\data\dataset")
    parser.add_argument("--output", default=r"c:\Users\shlok\Downloads\Hackathon-2\data\processed")
    parser.add_argument("--max-docs", type=int, default=50)
    parser.add_argument("--split", choices=["training", "testing", "all"], default="training")
    
    args = parser.parse_args()
    
    if args.action == "seed":
        asyncio.run(seed_funsd_to_supabase(
            args.dataset,
            max_docs=args.max_docs,
            split=args.split
        ))
    else:
        export_for_inference(
            args.dataset,
            args.output,
            max_docs=args.max_docs
        )
