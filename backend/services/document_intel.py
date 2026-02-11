"""
Document Intelligence Service
- OCR + layout understanding
- Field extraction with confidence
- PII detection & redaction
- Embedding generation for Vector DB
"""
import re
from typing import Dict, List, Optional, Tuple, Any
from uuid import UUID, uuid4
from datetime import datetime

from supabase import create_client
from sentence_transformers import SentenceTransformer

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    EMBEDDING_MODEL, EMBEDDING_DIMENSION,
    ENABLE_PII_DETECTION
)
from services.audit_service import log_ai_decision, log_audit_event
from services.doc_classifier import get_classifier

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
embedding_model = SentenceTransformer(EMBEDDING_MODEL)

# Initialize classifier
classifier = get_classifier(embedding_model)

# Try loading EasyOCR
try:
    import easyocr
    ocr_reader = easyocr.Reader(['en'], gpu=False) # CPU mode fallback
except ImportError:
    ocr_reader = None
    print("EasyOCR not found. Using mock OCR.")


async def upload_document(
    file_content: bytes,
    filename: str,
    doc_type: str,
    source_tier: str,
    uploader_id: UUID
) -> Dict[str, Any]:
    """
    Process uploaded document through OCR, Classification, and Extraction pipeline.
    """
    doc_id = uuid4()
    
    # Step 1: OCR
    raw_text = await perform_ocr(file_content, filename)
    
    # Step 2: Auto-Classification
    detected_type, type_confidence = classifier.classify(raw_text)
    
    # If user selected "auto", use detected type
    final_doc_type = detected_type if doc_type == "auto" else doc_type
    
    # Step 3: Extract fields
    extracted_fields, extraction_confidence = await extract_fields(raw_text, final_doc_type)
    
    # Step 4: PII Detection
    pii_detected, pii_locations = await detect_pii(raw_text)
    redacted_text = await redact_pii(raw_text, pii_locations) if pii_detected else raw_text
    
    # Step 5: Embeddings
    embedding_id = await generate_embeddings(doc_id, redacted_text)
    
    # Create document record
    doc_record = {
        "id": str(doc_id),
        "uploader_id": str(uploader_id),
        "title": filename,
        "doc_type": final_doc_type,
        "source_tier": source_tier,
        "raw_text": raw_text,
        "extracted_fields": extracted_fields,
        "pii_detected": pii_detected,
        "pii_redacted_text": redacted_text,
        "embedding_id": str(embedding_id),
        "status": "processed",
        "created_by": str(uploader_id),
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("documents").insert(doc_record).execute()
    
    # Validation Warning
    warning = None
    if doc_type != "auto" and final_doc_type != detected_type and type_confidence > 0.6:
        warning = f"User selected {doc_type}, but AI detected {detected_type} ({type_confidence:.0%})"
    
    # Log AI Decision
    await log_ai_decision(
        model_name="doc-intel-v2",
        model_version="2.0.0",
        module="document_intel",
        input_data={"filename": filename},
        output={
            "detected_type": detected_type, 
            "confidence": type_confidence,
            "fields_extracted": len(extracted_fields)
        },
        confidence=type_confidence,
        source_document_id=doc_id,
        explanation=f"Classified as {detected_type} with {type_confidence:.1%} confidence. {warning or ''}"
    )
    
    return doc_record


async def perform_ocr(file_content: bytes, filename: str) -> str:
    """Perform OCR using EasyOCR if available"""
    if filename.endswith('.txt'):
        return file_content.decode('utf-8', errors='ignore')
        
    try:
        # EasyOCR
        if ocr_reader:
            # EasyOCR expects bytes or path
            # reader.readtext(image, detail=0) returns list of strings
            import numpy as np
            from PIL import Image
            import io
            
            image = Image.open(io.BytesIO(file_content)).convert('RGB')
            # Convert to numpy array for EasyOCR
            image_np = np.array(image)
            
            result = ocr_reader.readtext(image_np, detail=0)
            return "\n".join(result)
            
        # Mock Fallback
        return f"[Mock OCR] Content of {filename}.\n Invoice #12345. Total: $500. Date: 2023-10-01."
        
    except Exception as e:
        print(f"OCR Failed: {e}")
        return ""


async def extract_fields(raw_text: str, doc_type: str) -> Tuple[List[Dict], float]:
    """Extract structured fields based on doc_type (Regex + LayoutLM placeholder)"""
    fields = []
    confidence_scores = []
    
    patterns = get_field_patterns(doc_type)
    
    for field_name, pattern in patterns.items():
        matches = re.findall(pattern, raw_text, re.IGNORECASE)
        if matches:
            val = matches[0] if isinstance(matches[0], str) else matches[0][0]
            fields.append({
                "name": field_name,
                "value": val,
                "confidence": 0.9,
                "type": "extracted"
            })
            confidence_scores.append(0.9)
            
    return fields, (sum(confidence_scores)/len(confidence_scores) if fields else 0.5)


def get_field_patterns(doc_type: str) -> Dict[str, str]:
    """Return field extraction patterns based on document type"""
    patterns = {
        "policy": {
            "policy_number": r'Policy\s*(?:No|Number)[:\s]*([A-Z0-9-]+)',
            "effective_date": r'Effective\s*(?:Date|From)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            "department": r'Department[:\s]*([A-Za-z\s]+)'
        },
        "gazette": {
            "gazette_number": r'Gazette\s*(?:No|Number)[:\s]*([A-Z0-9-]+)',
            "published_date": r'Published[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        },
        "application": {
            "applicant_name": r'Name[:\s]*([A-Za-z\s]+)',
            "application_id": r'Application\s*(?:ID|No)[:\s]*([A-Z0-9-]+)',
            "date": r'Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        },
        "receipt": {
            "receipt_number": r'Receipt\s*(?:No|Number)[:\s]*([A-Z0-9-]+)',
            "amount": r'(?:Amount|Total)[:\s]*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)',
            "date": r'Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        }
    }
    return patterns.get(doc_type, patterns["application"])


async def detect_pii(text: str) -> Tuple[bool, Dict[str, List]]:
    """Detect PII in text and return locations"""
    if not ENABLE_PII_DETECTION:
        return False, {}
    
    pii_locations = {}
    pii_found = False
    
    for pii_type, pattern in PII_PATTERNS.items():
        matches = list(re.finditer(pattern, text))
        if matches:
            pii_found = True
            pii_locations[pii_type] = [(m.start(), m.end(), m.group()) for m in matches]
    
    return pii_found, pii_locations


async def redact_pii(text: str, pii_locations: Dict[str, List]) -> str:
    """Redact PII from text"""
    redacted = text
    
    # Sort all matches by position (reverse to preserve indices)
    all_matches = []
    for pii_type, locations in pii_locations.items():
        for start, end, value in locations:
            all_matches.append((start, end, pii_type))
    
    all_matches.sort(key=lambda x: x[0], reverse=True)
    
    for start, end, pii_type in all_matches:
        redacted = redacted[:start] + f"[REDACTED_{pii_type.upper()}]" + redacted[end:]
    
    return redacted


async def generate_embeddings(doc_id: UUID, text: str) -> UUID:
    """Generate and store embeddings for document text"""
    # Chunk text for embedding
    chunks = chunk_text(text, max_length=512)
    
    vector_ids = []
    for i, chunk in enumerate(chunks):
        vector_id = uuid4()
        
        # Generate embedding
        embedding = embedding_model.encode(chunk).tolist()
        
        # Store in vectors table
        vector_record = {
            "id": str(vector_id),
            "embedding": embedding,
            "source_ref": str(doc_id),
            "source_type": "document",
            "doc_id": str(doc_id),
            "page": i + 1,
            "chunk_text": chunk,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("vectors").insert(vector_record).execute()
        vector_ids.append(vector_id)
    
    return vector_ids[0] if vector_ids else uuid4()


def chunk_text(text: str, max_length: int = 512) -> List[str]:
    """Split text into chunks for embedding"""
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 > max_length:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
        else:
            current_chunk.append(word)
            current_length += len(word) + 1
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks if chunks else [text]


async def get_document(doc_id: UUID) -> Optional[Dict]:
    """Retrieve document by ID"""
    result = supabase.table("documents").select("*").eq("id", str(doc_id)).single().execute()
    return result.data


async def search_documents(query: str, limit: int = 5) -> List[Dict]:
    """Search documents using embedding similarity"""
    # Generate query embedding
    query_embedding = embedding_model.encode(query).tolist()
    
    # Perform vector similarity search (using Supabase RPC)
    # Note: Requires a Supabase function for vector search
    results = supabase.rpc(
        'match_documents',
        {'query_embedding': query_embedding, 'match_threshold': 0.7, 'match_count': limit}
    ).execute()
    
    return results.data if results.data else []
