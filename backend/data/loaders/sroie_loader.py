"""
SROIE (Scanned Receipts OCR and Information Extraction) Data Loader
Loads receipt images and ground truth for Expense Categorization.

Dataset Structure (Typical):
- key/ (Entities: Company, Date, Address, Total)
- img/ (Receipt Images)
- box/ (Bounding Boxes)
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Generator, Tuple
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Receipt:
    """Receipt representation"""
    id: str
    image_path: str
    company: Optional[str] = None
    date: Optional[str] = None
    address: Optional[str] = None
    total: Optional[str] = None
    raw_text: Optional[str] = None
    
    # Metadata
    category: str = "uncategorized"
    
class SROIELoader:
    """
    Loads receipts from SROIE dataset.
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\urbikn\sroie-datasetv2\versions\4"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        
    def find_data_dirs(self) -> Tuple[Path, Path]:
        """Attempt to locate img and key directories"""
        # Search recursively for a directory containing '000.jpg' or similar
        # and a directory containing '000.json' or '000.txt'
        
        img_dir = None
        key_dir = None
        
        for root, dirs, files in os.walk(self.dataset_path):
            if any(f.endswith('.jpg') for f in files):
                img_dir = Path(root)
            if any(f.endswith('.json') for f in files) or any(f.endswith('.txt') and 'key' in root.lower() for f in files):
                key_dir = Path(root)
                
            if img_dir and key_dir:
                break
                
        return img_dir, key_dir

    def load(self, max_receipts: Optional[int] = None) -> Generator[Receipt, None, None]:
        """Load receipts"""
        img_dir, key_dir = self.find_data_dirs()
        
        if not img_dir or not key_dir:
            print(f"Warning: Could not locate 'img' or 'key' directories in {self.dataset_path}")
            return
            
        print(f"Loading from:\n  Images: {img_dir}\n  Keys: {key_dir}")
        
        count = 0
        for img_file in img_dir.glob("*.jpg"):
            if max_receipts and count >= max_receipts:
                break
                
            file_id = img_file.stem
            
            # Try to find corresponding key file (json or txt)
            key_file = key_dir / f"{file_id}.json"
            if not key_file.exists():
                key_file = key_dir / f"{file_id}.txt"
                
            company, date, address, total = None, None, None, None
            
            if key_file.exists():
                try:
                    with open(key_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if key_file.suffix == '.json':
                            data = json.loads(content)
                            company = data.get('company')
                            date = data.get('date')
                            address = data.get('address')
                            total = data.get('total')
                        else:
                            # Parse TXT (usually JSON-like or strict format)
                            # Fallback: naive line reading or try json.loads if valid
                            try:
                                data = json.loads(content)
                                company = data.get('company')
                                date = data.get('date')
                                address = data.get('address')
                                total = data.get('total')
                            except:
                                pass # Manual parsing logic if needed
                except Exception as e:
                    print(f"Error reading key file {key_file}: {e}")

            # Categorize based on company name (heuristic)
            category = self._categorize(company)
            
            yield Receipt(
                id=file_id,
                image_path=str(img_file),
                company=company,
                date=date,
                address=address,
                total=total,
                category=category
            )
            count += 1

    def _categorize(self, company: Optional[str]) -> str:
        """Categorize expense based on company name"""
        if not company:
            return "uncategorized"
        
        c_lower = company.lower()
        if any(x in c_lower for x in ['mart', 'supermarket', 'grocery', 'store', 'eleven']):
            return "supplies"
        if any(x in c_lower for x in ['restaurant', 'cafe', 'coffee', 'food', 'bistro', 'kitchen']):
            return "food" # Map to 'welfare' or 'supplies' depending on gov context
        if any(x in c_lower for x in ['book', 'stationary', 'office']):
            return "supplies"
        if any(x in c_lower for x in ['pharmacy', 'health', 'clinic', 'hospital']):
            return "welfare"
        if any(x in c_lower for x in ['shell', 'petronas', 'caltex', 'oil', 'fuel']):
            return "transport"
        if any(x in c_lower for x in ['hotel', 'resort', 'travel']):
            return "transport"
            
        return "other"
            
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        img_dir, _ = self.find_data_dirs()
        if not img_dir:
            return {"total": 0}
            
        return {
            "total": len(list(img_dir.glob("*.jpg")))
        }

# CLI
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("  SROIE Data Loader")
    print(f"{'='*60}\n")
    
    try:
        loader = SROIELoader()
        stats = loader.get_statistics()
        print(f"   Total Receipts: {stats['total']}")
        
        print("\n   Sample Receipts:")
        for receipt in loader.load(max_receipts=3):
            print(f"     ID: {receipt.id}")
            print(f"     Company: {receipt.company}")
            print(f"     Date: {receipt.date}")
            print(f"     Total: {receipt.total}")
            print(f"     Category: {receipt.category}")
            print("-" * 30)
            
        print(f"\n{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
