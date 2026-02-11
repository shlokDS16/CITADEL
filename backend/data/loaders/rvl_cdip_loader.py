"""
RVL-CDIP Data Loader
Loads and processes the Ryerson Vision Lab Complex Document Information Processing dataset.
Used for document classification (16 classes).

Dataset Structure:
- data_final/images[a-z]/.../*.tif
- labels_final.csv (path, label)
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Generator, Tuple
from dataclasses import dataclass
from PIL import Image

@dataclass
class DocumentImage:
    """Document Image representation"""
    id: str
    image_path: str
    label_id: int
    label_name: str

class RVLCDIPLoader:
    """
    Loads documents from the RVL-CDIP dataset.
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\gowtamsingulur\rvlcdip\versions\1"
    
    CLASSES = {
        0: "letter",
        1: "form",
        2: "email",
        3: "handwritten",
        4: "advertisement",
        5: "scientific report",
        6: "scientific publication",
        7: "specification",
        8: "file folder",
        9: "news article",
        10: "budget",
        11: "invoice",
        12: "presentation",
        13: "questionnaire",
        14: "resume",
        15: "memo"
    }

    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.labels_file = self.dataset_path / "labels_final.csv"
        self.data_dir = self.dataset_path / "data_final"
        
        if not self.labels_file.exists():
             raise FileNotFoundError(f"RVL-CDIP labels file not found at: {self.labels_file}")
        
        self.df = pd.read_csv(self.labels_file)

    def load(self, max_docs: Optional[int] = None) -> Generator[DocumentImage, None, None]:
        """Load document images"""
        df = self.df
        if max_docs:
            df = df.head(max_docs)
            
        for _, row in df.iterrows():
            rel_path = row['path']
            label_id = int(row['label'])
            full_path = self.data_dir / rel_path
            
            # Construct ID from path (e.g., "voh71d00/509132755+-2755")
            # Usually the last two parts of the path are unique enough
            path_parts = Path(rel_path).parts
            doc_id = "_".join(path_parts[-2:]) if len(path_parts) >= 2 else Path(rel_path).stem

            if full_path.exists():
                yield DocumentImage(
                    id=doc_id,
                    image_path=str(full_path),
                    label_id=label_id,
                    label_name=self.CLASSES.get(label_id, "unknown")
                )

    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        stats = {
            "total": len(self.df),
            "by_label": {}
        }
        
        label_counts = self.df['label'].value_counts()
        for label_id, count in label_counts.items():
            class_name = self.CLASSES.get(label_id, str(label_id))
            stats["by_label"][class_name] = int(count)
            
        return stats

# CLI
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("  RVL-CDIP Data Loader")
    print(f"{'='*60}\n")
    
    try:
        loader = RVLCDIPLoader()
        stats = loader.get_statistics()
        
        print(f"   Total Documents: {stats['total']}")
        print("   Class Distribution:")
        for cls_name, count in sorted(stats['by_label'].items(), key=lambda x: x[1], reverse=True)[:5]:
             print(f"     - {cls_name}: {count}")
             
        print("\n   Sample Documents:")
        for doc in loader.load(max_docs=3):
            print(f"     ID: {doc.id}")
            print(f"     Label: {doc.label_name} ({doc.label_id})")
            print(f"     Path: {doc.image_path}")

        print(f"\n{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
