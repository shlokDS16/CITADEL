"""
FUNSD Data Loader
Loads Form Understanding in Noisy Scanned Documents dataset
for Document Intelligence training/inference.

Dataset structure:
- training_data/
  - images/ (PNG files)
  - annotations/ (JSON files)
- testing_data/
  - images/
  - annotations/

Annotation format:
{
  "form": [
    {
      "id": 0,
      "text": "Field text",
      "box": [x1, y1, x2, y2],
      "label": "header|question|answer|other",
      "words": [...],
      "linking": [[from_id, to_id], ...]
    }
  ]
}
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Generator
from dataclasses import dataclass, field
from PIL import Image
import numpy as np


@dataclass
class Word:
    """Individual word with bounding box"""
    text: str
    box: Tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass 
class FormField:
    """A form field (header, question, answer, or other)"""
    id: int
    text: str
    box: Tuple[int, int, int, int]
    label: str  # header, question, answer, other
    words: List[Word]
    linking: List[Tuple[int, int]]  # Links to other fields


@dataclass
class FormDocument:
    """A complete form document with image and annotations"""
    doc_id: str
    image_path: Path
    fields: List[FormField]
    
    # Derived properties
    @property
    def questions(self) -> List[FormField]:
        return [f for f in self.fields if f.label == "question"]
    
    @property
    def answers(self) -> List[FormField]:
        return [f for f in self.fields if f.label == "answer"]
    
    @property
    def headers(self) -> List[FormField]:
        return [f for f in self.fields if f.label == "header"]
    
    @property
    def qa_pairs(self) -> List[Tuple[FormField, FormField]]:
        """Extract question-answer pairs based on linking"""
        pairs = []
        field_map = {f.id: f for f in self.fields}
        
        for field in self.questions:
            for link in field.linking:
                answer_id = link[1] if link[0] == field.id else link[0]
                if answer_id in field_map:
                    answer_field = field_map[answer_id]
                    if answer_field.label == "answer":
                        pairs.append((field, answer_field))
        
        return pairs
    
    @property
    def full_text(self) -> str:
        """Get all text from document"""
        return " ".join(f.text for f in self.fields if f.text.strip())


class FUNSDLoader:
    """
    Loader for FUNSD dataset.
    
    Usage:
        loader = FUNSDLoader("path/to/funsd/dataset")
        for doc in loader.load_training():
            print(doc.doc_id, len(doc.fields))
    """
    
    def __init__(self, dataset_path: str):
        self.dataset_path = Path(dataset_path)
        self.training_path = self.dataset_path / "training_data"
        self.testing_path = self.dataset_path / "testing_data"
        
        # Validate paths
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset path not found: {dataset_path}")
    
    def _parse_annotation(self, annotation_path: Path) -> List[FormField]:
        """Parse a single annotation JSON file"""
        with open(annotation_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        fields = []
        for item in data.get("form", []):
            words = [
                Word(
                    text=w.get("text", ""),
                    box=tuple(w.get("box", [0, 0, 0, 0]))
                )
                for w in item.get("words", [])
            ]
            
            field = FormField(
                id=item.get("id", 0),
                text=item.get("text", ""),
                box=tuple(item.get("box", [0, 0, 0, 0])),
                label=item.get("label", "other"),
                words=words,
                linking=[tuple(link) for link in item.get("linking", [])]
            )
            fields.append(field)
        
        return fields
    
    def _load_split(self, split_path: Path) -> Generator[FormDocument, None, None]:
        """Load documents from a split (training or testing)"""
        annotations_path = split_path / "annotations"
        images_path = split_path / "images"
        
        if not annotations_path.exists():
            raise FileNotFoundError(f"Annotations path not found: {annotations_path}")
        
        for annotation_file in sorted(annotations_path.glob("*.json")):
            doc_id = annotation_file.stem
            image_file = images_path / f"{doc_id}.png"
            
            # Parse annotation
            fields = self._parse_annotation(annotation_file)
            
            yield FormDocument(
                doc_id=doc_id,
                image_path=image_file,
                fields=fields
            )
    
    def load_training(self) -> Generator[FormDocument, None, None]:
        """Load training documents"""
        return self._load_split(self.training_path)
    
    def load_testing(self) -> Generator[FormDocument, None, None]:
        """Load testing documents"""
        return self._load_split(self.testing_path)
    
    def load_all(self) -> Generator[FormDocument, None, None]:
        """Load all documents (training + testing)"""
        yield from self.load_training()
        yield from self.load_testing()
    
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        stats = {
            "training": {"docs": 0, "fields": 0, "questions": 0, "answers": 0, "qa_pairs": 0},
            "testing": {"docs": 0, "fields": 0, "questions": 0, "answers": 0, "qa_pairs": 0}
        }
        
        for doc in self.load_training():
            stats["training"]["docs"] += 1
            stats["training"]["fields"] += len(doc.fields)
            stats["training"]["questions"] += len(doc.questions)
            stats["training"]["answers"] += len(doc.answers)
            stats["training"]["qa_pairs"] += len(doc.qa_pairs)
        
        for doc in self.load_testing():
            stats["testing"]["docs"] += 1
            stats["testing"]["fields"] += len(doc.fields)
            stats["testing"]["questions"] += len(doc.questions)
            stats["testing"]["answers"] += len(doc.answers)
            stats["testing"]["qa_pairs"] += len(doc.qa_pairs)
        
        stats["total"] = {
            "docs": stats["training"]["docs"] + stats["testing"]["docs"],
            "fields": stats["training"]["fields"] + stats["testing"]["fields"],
            "questions": stats["training"]["questions"] + stats["testing"]["questions"],
            "answers": stats["training"]["answers"] + stats["testing"]["answers"],
            "qa_pairs": stats["training"]["qa_pairs"] + stats["testing"]["qa_pairs"]
        }
        
        return stats


def extract_key_value_pairs(doc: FormDocument) -> List[Dict]:
    """
    Extract key-value pairs from a form document.
    Returns list of {question, answer, question_box, answer_box}
    """
    pairs = []
    for question, answer in doc.qa_pairs:
        pairs.append({
            "question": question.text,
            "answer": answer.text,
            "question_box": question.box,
            "answer_box": answer.box
        })
    return pairs


def prepare_for_ocr(doc: FormDocument) -> Dict:
    """
    Prepare document for OCR training/evaluation.
    Returns ground truth text with bounding boxes.
    """
    ocr_data = {
        "doc_id": doc.doc_id,
        "image_path": str(doc.image_path),
        "words": []
    }
    
    for field in doc.fields:
        for word in field.words:
            if word.text.strip():
                ocr_data["words"].append({
                    "text": word.text,
                    "box": word.box
                })
    
    return ocr_data


def prepare_for_ner(doc: FormDocument) -> Dict:
    """
    Prepare document for NER (Named Entity Recognition) format.
    Uses BIO tagging: B-LABEL, I-LABEL, O
    """
    tokens = []
    labels = []
    boxes = []
    
    for field in doc.fields:
        for i, word in enumerate(field.words):
            if not word.text.strip():
                continue
            
            tokens.append(word.text)
            boxes.append(word.box)
            
            if field.label == "other":
                labels.append("O")
            elif i == 0:
                labels.append(f"B-{field.label.upper()}")
            else:
                labels.append(f"I-{field.label.upper()}")
    
    return {
        "doc_id": doc.doc_id,
        "tokens": tokens,
        "labels": labels,
        "boxes": boxes
    }


# CLI for testing
if __name__ == "__main__":
    import sys
    
    # Default path
    dataset_path = r"c:\Users\shlok\Downloads\Hackathon-2\data\dataset"
    
    if len(sys.argv) > 1:
        dataset_path = sys.argv[1]
    
    print(f"\n{'='*60}")
    print("  FUNSD Data Loader")
    print(f"{'='*60}")
    print(f"\nDataset path: {dataset_path}\n")
    
    try:
        loader = FUNSDLoader(dataset_path)
        
        # Get statistics
        print("Loading statistics...")
        stats = loader.get_statistics()
        
        print(f"\n📊 Dataset Statistics:")
        print(f"  Training: {stats['training']['docs']} documents")
        print(f"    - Fields: {stats['training']['fields']}")
        print(f"    - Questions: {stats['training']['questions']}")
        print(f"    - Answers: {stats['training']['answers']}")
        print(f"    - Q&A Pairs: {stats['training']['qa_pairs']}")
        
        print(f"\n  Testing: {stats['testing']['docs']} documents")
        print(f"    - Fields: {stats['testing']['fields']}")
        print(f"    - Q&A Pairs: {stats['testing']['qa_pairs']}")
        
        print(f"\n  Total: {stats['total']['docs']} documents, {stats['total']['qa_pairs']} Q&A pairs")
        
        # Show sample document
        print(f"\n{'='*60}")
        print("  Sample Document")
        print(f"{'='*60}")
        
        sample = next(loader.load_training())
        print(f"\nDoc ID: {sample.doc_id}")
        print(f"Image: {sample.image_path}")
        print(f"Fields: {len(sample.fields)}")
        print(f"Headers: {len(sample.headers)}")
        print(f"Q&A Pairs: {len(sample.qa_pairs)}")
        
        print("\nSample Q&A Pairs:")
        for q, a in sample.qa_pairs[:5]:
            print(f"  Q: {q.text[:50]}...")
            print(f"  A: {a.text[:50]}...")
            print()
        
        print(f"{'='*60}")
        print("  ✅ FUNSD Loader Ready!")
        print(f"{'='*60}\n")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
