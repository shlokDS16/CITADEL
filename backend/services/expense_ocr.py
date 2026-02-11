"""
Expense OCR Service
Extracts key information from receipt images using EasyOCR and regex.

Fields: Merchant, Date, Total, Address, Items
"""
import re
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from PIL import Image
import io

# Try loading EasyOCR (GPU or CPU)
try:
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False) # CPU mode
except ImportError:
    reader = None

def extract_receipt_info(image_bytes: bytes) -> Dict[str, Any]:
    """
    Extract structured data from receipt image.
    Returns: {merchant, date, total, address, items, raw_text}
    """
    if not reader:
        return {"error": "OCR engine not available"}
        
    try:
        # Load image
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        image_np = np.array(image)
        
        # Perform OCR
        # detail=0 returns text list
        result = reader.readtext(image_np, detail=0)
        raw_text = "\n".join(result)
        
        # Extract fields using regex/heuristics
        merchant = _extract_merchant(result)
        date_str = _extract_date(raw_text)
        total = _extract_total(raw_text)
        address = _extract_address(raw_text)
        
        return {
            "merchant": merchant,
            "date": date_str,
            "total": total,
            "address": address,
            "raw_text": raw_text,
            "items": _extract_items(result)
        }
    except Exception as e:
        print(f"OCR Extraction Failed: {e}")
        return {"error": str(e), "raw_text": ""}

def _extract_merchant(lines: List[str]) -> str:
    """Extract merchant name (usually first line with substantial text)"""
    for line in lines[:3]: # check top 3 lines
        if len(line.strip()) > 3 and not re.search(r'\d', line):
            return line.strip()
    return "Unknown Merchant"

def _extract_date(text: str) -> Optional[str]:
    """Extract date from text"""
    # DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, DD.MM.YYYY
    date_patterns = [
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def _extract_total(text: str) -> Optional[float]:
    """Extract total amount"""
    # Look for "Total", "Amount", "Balance Due"
    # Or just largest number with currency symbol
    
    total_patterns = [
        r'(?:Total|Amount|Balance|Due)[^0-9]*([\d,]+\.\d{2})',
        r'(?:RM|Rs\.?|USD|EUR)\s*([\d,]+\.\d{2})'
    ]
    
    amounts = []
    
    for pattern in total_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                amounts.append(float(m.replace(',', '')))
            except: 
                pass
                
    if amounts:
        return max(amounts) # Usually total is the largest amount
        
    return 0.0

def _extract_address(text: str) -> Optional[str]:
    """Extract address (heuristic: lines with numbers and words, usually after merchant)"""
    # Hard to do with regex only, requires Named Entity Recognition (NER)
    # Placeholder
    return None

def _extract_items(lines: List[str]) -> List[Dict]:
    """Extract line items (products + price)"""
    items = []
    # Heuristic: Line ending in a price like 12.99
    price_pattern = r'(\d+\.\d{2})$'
    
    for line in lines:
        match = re.search(price_pattern, line.strip())
        if match:
            price_str = match.group(1)
            item_name = line[:match.start()].strip()
            if len(item_name) > 3 and "total" not in item_name.lower():
                try:
                    price = float(price_str)
                    items.append({"name": item_name, "price": price})
                except:
                    pass
    return items
