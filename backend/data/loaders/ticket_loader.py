"""
Ticket Analyzer Data Loader
Loads and processes ticket datasets for classification.

Datasets:
1. Email Tickets (Multi-language) - 200 labeled tickets
2. GitHub Issues/Helpdesk - 15,955 tickets with detailed metadata

Combined fields we extract:
- text: ticket content
- category: queue/type
- priority: 1-5 scale
- language: en, fr, es, de
"""
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Generator
from dataclasses import dataclass, field
from enum import Enum


class Priority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    MINIMAL = 5


@dataclass
class Ticket:
    """Unified ticket representation"""
    id: str
    title: str
    description: str
    category: str
    subcategory: Optional[str] = None
    priority: int = 3  # 1-5 scale
    language: str = "en"
    source: str = "unknown"
    labels: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    @property
    def full_text(self) -> str:
        """Combined title and description"""
        return f"{self.title}\n\n{self.description}"
    
    @property
    def priority_label(self) -> str:
        """Convert numeric priority to label"""
        labels = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "minimal"}
        return labels.get(self.priority, "medium")


class EmailTicketLoader:
    """
    Loads the email ticket dataset (multi-language helpdesk).
    Small but well-labeled dataset (200 tickets).
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\tobiasbueck\email-ticket-text-german-classification\versions\5"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.csv_file = self.dataset_path / "ticket_helpdesk_labeled_multi_languages_english_spain_french_german.csv"
        
        if not self.csv_file.exists():
            raise FileNotFoundError(f"Dataset not found: {self.csv_file}")
    
    def load(self) -> Generator[Ticket, None, None]:
        """Load all email tickets"""
        df = pd.read_csv(self.csv_file)
        
        for idx, row in df.iterrows():
            yield Ticket(
                id=f"email_{idx}",
                title=str(row.get("subject", "")),
                description=str(row.get("text", "")),
                category=str(row.get("queue", "general")),
                subcategory=str(row.get("software_used", "")) or str(row.get("hardware_used", "")),
                priority=int(row.get("priority", 3)),
                language=str(row.get("language", "en")),
                source="email_helpdesk",
                labels=[],
                metadata={
                    "software_used": row.get("software_used"),
                    "hardware_used": row.get("hardware_used"),
                    "accounting_category": row.get("accounting_category")
                }
            )
    
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        df = pd.read_csv(self.csv_file)
        return {
            "total": len(df),
            "by_category": df["queue"].value_counts().to_dict(),
            "by_priority": df["priority"].value_counts().to_dict(),
            "by_language": df["language"].value_counts().to_dict()
        }


class GitHubTicketLoader:
    """
    Loads GitHub issues dataset.
    Large dataset (15,955 issues) with rich metadata.
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\tobiasbueck\helpdesk-github-tickets\versions\6"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.csv_file = self.dataset_path / "github_issues_tickets.csv"
        
        if not self.csv_file.exists():
            raise FileNotFoundError(f"Dataset not found: {self.csv_file}")
    
    def load(self, max_tickets: Optional[int] = None) -> Generator[Ticket, None, None]:
        """Load GitHub issues as tickets"""
        df = pd.read_csv(self.csv_file, low_memory=False)
        
        if max_tickets:
            df = df.head(max_tickets)
        
        for idx, row in df.iterrows():
            # Extract labels
            labels = []
            for i in range(10):  # Check first 10 label columns
                label = row.get(f"labels_{i}_name")
                if pd.notna(label):
                    labels.append(str(label))
            
            # Map state to priority (closed = lower priority for demo)
            state = str(row.get("state", "open"))
            priority = 3 if state == "open" else 4
            
            # Determine category from labels
            category = self._categorize_from_labels(labels)
            
            yield Ticket(
                id=f"github_{row.get('id', idx)}",
                title=str(row.get("title", "")),
                description=str(row.get("body", "") or ""),
                category=category,
                subcategory=str(row.get("repo_name", "")),
                priority=priority,
                language="en",
                source="github_issues",
                labels=labels,
                metadata={
                    "state": state,
                    "repo_name": row.get("repo_name"),
                    "reactions_total": row.get("reactions_total_count"),
                    "comments_count": row.get("comments")
                }
            )
    
    def _categorize_from_labels(self, labels: List[str]) -> str:
        """Infer category from GitHub labels"""
        labels_lower = [l.lower() for l in labels]
        
        if any("bug" in l for l in labels_lower):
            return "bug"
        elif any("feature" in l or "enhancement" in l for l in labels_lower):
            return "feature_request"
        elif any("doc" in l for l in labels_lower):
            return "documentation"
        elif any("question" in l or "help" in l for l in labels_lower):
            return "question"
        elif any("security" in l for l in labels_lower):
            return "security"
        else:
            return "general"
    
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        df = pd.read_csv(self.csv_file, low_memory=False)
        
        # Count labels
        label_counts = {}
        for i in range(10):
            col = f"labels_{i}_name"
            if col in df.columns:
                for label in df[col].dropna():
                    label_counts[label] = label_counts.get(label, 0) + 1
        
        return {
            "total": len(df),
            "by_state": df["state"].value_counts().to_dict() if "state" in df.columns else {},
            "by_repo": df["repo_name"].value_counts().head(10).to_dict() if "repo_name" in df.columns else {},
            "top_labels": dict(sorted(label_counts.items(), key=lambda x: x[1], reverse=True)[:20])
        }


class UnifiedTicketLoader:
    """
    Unified loader that combines both datasets.
    """
    
    def __init__(
        self,
        email_path: Optional[str] = None,
        github_path: Optional[str] = None
    ):
        self.email_loader = EmailTicketLoader(email_path)
        self.github_loader = GitHubTicketLoader(github_path)
    
    def load_all(
        self,
        include_email: bool = True,
        include_github: bool = True,
        max_github: int = 1000
    ) -> Generator[Ticket, None, None]:
        """Load tickets from all sources"""
        if include_email:
            yield from self.email_loader.load()
        
        if include_github:
            yield from self.github_loader.load(max_tickets=max_github)
    
    def get_training_data(self, max_samples: int = 500) -> List[Dict]:
        """
        Get training data in format ready for classification.
        Returns list of {text, category, priority}
        """
        data = []
        
        for ticket in self.load_all(max_github=max_samples):
            data.append({
                "id": ticket.id,
                "text": ticket.full_text,
                "category": ticket.category,
                "priority": ticket.priority,
                "priority_label": ticket.priority_label,
                "source": ticket.source
            })
            
            if len(data) >= max_samples:
                break
        
        return data
    
    def get_statistics(self) -> Dict:
        """Get combined statistics"""
        return {
            "email_tickets": self.email_loader.get_statistics(),
            "github_tickets": self.github_loader.get_statistics()
        }


def export_for_inference(
    output_path: str,
    max_samples: int = 500
):
    """Export tickets in inference-ready format"""
    print(f"\n{'='*60}")
    print("  Ticket Data Export")
    print(f"{'='*60}\n")
    
    loader = UnifiedTicketLoader()
    data = loader.get_training_data(max_samples)
    
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "tickets_inference_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"  📁 Saved to: {output_file}")
    print(f"  📊 Total tickets: {len(data)}")
    
    # Category breakdown
    categories = {}
    for item in data:
        cat = item["category"]
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"\n  Categories:")
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        print(f"    {cat}: {count}")
    
    print(f"\n{'='*60}\n")
    return len(data)


# CLI
if __name__ == "__main__":
    import sys
    
    print(f"\n{'='*60}")
    print("  Ticket Analyzer Data Loader")
    print(f"{'='*60}\n")
    
    try:
        loader = UnifiedTicketLoader()
        
        # Email tickets stats
        print("📧 Email Tickets Dataset:")
        email_stats = loader.email_loader.get_statistics()
        print(f"   Total: {email_stats['total']}")
        print(f"   Categories: {email_stats['by_category']}")
        print(f"   Languages: {email_stats['by_language']}")
        
        # GitHub tickets stats
        print("\n🐙 GitHub Tickets Dataset:")
        github_stats = loader.github_loader.get_statistics()
        print(f"   Total: {github_stats['total']}")
        print(f"   By State: {github_stats['by_state']}")
        print(f"   Top Labels: {list(github_stats['top_labels'].keys())[:10]}")
        
        # Sample tickets
        print(f"\n{'='*60}")
        print("  Sample Tickets")
        print(f"{'='*60}")
        
        for i, ticket in enumerate(loader.load_all(max_github=3)):
            if i >= 5:
                break
            print(f"\n  [{ticket.source}] {ticket.category.upper()}")
            print(f"  Title: {ticket.title[:60]}...")
            print(f"  Priority: {ticket.priority_label}")
        
        # Export
        print(f"\n{'='*60}")
        export_for_inference(
            r"c:\Users\shlok\Downloads\Hackathon-2\data\processed",
            max_samples=500
        )
        
        print("  ✅ Ticket Loader Ready!")
        print(f"{'='*60}\n")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
