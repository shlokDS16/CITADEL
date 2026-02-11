"""
Fake News Detection Data Loader
Loads and processes fake news datasets for classification.

Datasets:
1. LIAR - Political statements with 6-way labels (10k+ samples)
2. FakeNewsNet - News articles with binary labels (23k+ samples)

Labels:
- LIAR: pants-fire, false, barely-true, half-true, mostly-true, true
- FakeNewsNet: fake (0), real (1)
"""
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Generator
from dataclasses import dataclass, field
from enum import Enum


class VeracityLabel(Enum):
    """Unified veracity labels (6-point scale like LIAR)"""
    PANTS_FIRE = 0  # Completely false
    FALSE = 1       # False
    BARELY_TRUE = 2 # Mostly false with some truth
    HALF_TRUE = 3   # Mix of true and false
    MOSTLY_TRUE = 4 # Mostly true with minor issues  
    TRUE = 5        # Completely true
    
    @classmethod
    def from_liar(cls, label: str) -> 'VeracityLabel':
        """Convert LIAR label string to enum"""
        mapping = {
            'pants-fire': cls.PANTS_FIRE,
            'false': cls.FALSE,
            'barely-true': cls.BARELY_TRUE,
            'half-true': cls.HALF_TRUE,
            'mostly-true': cls.MOSTLY_TRUE,
            'true': cls.TRUE
        }
        return mapping.get(label.lower(), cls.HALF_TRUE)
    
    @classmethod  
    def from_binary(cls, is_real: int) -> 'VeracityLabel':
        """Convert binary label (0=fake, 1=real) to enum"""
        return cls.TRUE if is_real == 1 else cls.FALSE
    
    @property
    def is_fake(self) -> bool:
        """Binary classification: consider barely-true and below as fake"""
        return self.value <= 2
    
    @property
    def confidence_score(self) -> float:
        """Convert to 0-1 confidence score (how true it is)"""
        return self.value / 5.0


@dataclass
class NewsArticle:
    """Unified news article representation"""
    id: str
    text: str
    label: VeracityLabel
    source: str = "unknown"
    
    # Optional metadata
    title: Optional[str] = None
    speaker: Optional[str] = None
    subject: Optional[str] = None
    context: Optional[str] = None
    source_url: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    @property
    def is_fake(self) -> bool:
        return self.label.is_fake
    
    @property
    def label_name(self) -> str:
        return self.label.name.lower().replace('_', '-')
    
    @property
    def binary_label(self) -> int:
        """0 = fake, 1 = real"""
        return 0 if self.is_fake else 1


class LIARLoader:
    """
    Loads LIAR dataset - Political statements fact-checked by PolitiFact.
    ~12,800 statements with 6-way classification.
    
    Columns: id, label, statement, subject, speaker, job, state, party, 
             barely_true_count, false_count, half_true_count, mostly_true_count,
             pants_fire_count, context
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\doanquanvietnamca\liar-dataset\versions\1"
    
    COLUMNS = [
        'id', 'label', 'statement', 'subject', 'speaker', 'job', 'state', 'party',
        'barely_true_count', 'false_count', 'half_true_count', 
        'mostly_true_count', 'pants_fire_count', 'context'
    ]
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        
        self.train_file = self.dataset_path / "train.tsv"
        self.valid_file = self.dataset_path / "valid.tsv"
        self.test_file = self.dataset_path / "test.tsv"
        
        if not self.train_file.exists():
            raise FileNotFoundError(f"LIAR dataset not found: {self.train_file}")
    
    def _load_split(self, filepath: Path) -> Generator[NewsArticle, None, None]:
        """Load a single split file"""
        df = pd.read_csv(filepath, sep='\t', header=None, names=self.COLUMNS)
        
        for _, row in df.iterrows():
            yield NewsArticle(
                id=f"liar_{row['id']}",
                text=str(row['statement']),
                label=VeracityLabel.from_liar(str(row['label'])),
                source="liar_politifact",
                title=None,
                speaker=str(row['speaker']) if pd.notna(row['speaker']) else None,
                subject=str(row['subject']) if pd.notna(row['subject']) else None,
                context=str(row['context']) if pd.notna(row['context']) else None,
                metadata={
                    'job': row['job'],
                    'state': row['state'],
                    'party': row['party'],
                    'credit_history': {
                        'barely_true': row['barely_true_count'],
                        'false': row['false_count'],
                        'half_true': row['half_true_count'],
                        'mostly_true': row['mostly_true_count'],
                        'pants_fire': row['pants_fire_count']
                    }
                }
            )
    
    def load_train(self) -> Generator[NewsArticle, None, None]:
        return self._load_split(self.train_file)
    
    def load_valid(self) -> Generator[NewsArticle, None, None]:
        return self._load_split(self.valid_file)
    
    def load_test(self) -> Generator[NewsArticle, None, None]:
        return self._load_split(self.test_file)
    
    def load_all(self) -> Generator[NewsArticle, None, None]:
        yield from self.load_train()
        yield from self.load_valid()
        yield from self.load_test()
    
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        train_df = pd.read_csv(self.train_file, sep='\t', header=None, names=self.COLUMNS)
        valid_df = pd.read_csv(self.valid_file, sep='\t', header=None, names=self.COLUMNS)
        test_df = pd.read_csv(self.test_file, sep='\t', header=None, names=self.COLUMNS)
        
        all_df = pd.concat([train_df, valid_df, test_df])
        
        return {
            "total": len(all_df),
            "train": len(train_df),
            "valid": len(valid_df),
            "test": len(test_df),
            "by_label": all_df['label'].value_counts().to_dict(),
            "by_party": all_df['party'].value_counts().head(5).to_dict()
        }


class FakeNewsNetLoader:
    """
    Loads FakeNewsNet dataset - News articles from PolitiFact & GossipCop.
    ~23,196 articles with binary classification.
    
    Columns: title, news_url, source_domain, tweet_num, real
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\algord\fake-news\versions\1"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.csv_file = self.dataset_path / "FakeNewsNet.csv"
        
        if not self.csv_file.exists():
            raise FileNotFoundError(f"FakeNewsNet not found: {self.csv_file}")
    
    def load(self, max_samples: Optional[int] = None) -> Generator[NewsArticle, None, None]:
        """Load all articles"""
        df = pd.read_csv(self.csv_file)
        
        if max_samples:
            df = df.head(max_samples)
        
        for idx, row in df.iterrows():
            yield NewsArticle(
                id=f"fakenewsnet_{idx}",
                text=str(row['title']),  # Only title available in this version
                label=VeracityLabel.from_binary(int(row['real'])),
                source="fakenewsnet",
                title=str(row['title']),
                source_url=str(row['news_url']) if pd.notna(row['news_url']) else None,
                metadata={
                    'source_domain': row['source_domain'],
                    'tweet_num': row['tweet_num']
                }
            )
    
    def get_statistics(self) -> Dict:
        """Get dataset statistics"""
        df = pd.read_csv(self.csv_file)
        
        return {
            "total": len(df),
            "real": int(df['real'].sum()),
            "fake": int((df['real'] == 0).sum()),
            "top_domains": df['source_domain'].value_counts().head(10).to_dict(),
            "avg_tweets": float(df['tweet_num'].mean())
        }


class UnifiedFakeNewsLoader:
    """
    Unified loader combining both datasets.
    """
    
    def __init__(
        self,
        liar_path: Optional[str] = None,
        fakenewsnet_path: Optional[str] = None
    ):
        self.liar_loader = LIARLoader(liar_path)
        self.fakenewsnet_loader = FakeNewsNetLoader(fakenewsnet_path)
    
    def load_all(
        self,
        include_liar: bool = True,
        include_fakenewsnet: bool = True,
        max_fakenewsnet: int = 5000
    ) -> Generator[NewsArticle, None, None]:
        """Load articles from all sources"""
        if include_liar:
            yield from self.liar_loader.load_all()
        
        if include_fakenewsnet:
            yield from self.fakenewsnet_loader.load(max_samples=max_fakenewsnet)
    
    def get_training_data(self, max_samples: int = 1000) -> List[Dict]:
        """
        Get training data in format ready for classification.
        Returns list of {text, label, is_fake, source}
        """
        data = []
        
        for article in self.load_all(max_fakenewsnet=max_samples):
            data.append({
                "id": article.id,
                "text": article.text,
                "label": article.label_name,
                "label_6way": article.label.value,
                "is_fake": article.is_fake,
                "binary_label": article.binary_label,
                "source": article.source,
                "speaker": article.speaker,
                "subject": article.subject
            })
            
            if len(data) >= max_samples:
                break
        
        return data
    
    def get_statistics(self) -> Dict:
        """Get combined statistics"""
        return {
            "liar": self.liar_loader.get_statistics(),
            "fakenewsnet": self.fakenewsnet_loader.get_statistics()
        }


def export_for_inference(output_path: str, max_samples: int = 1000):
    """Export fake news data in inference-ready format"""
    print(f"\n{'='*60}")
    print("  Fake News Data Export")
    print(f"{'='*60}\n")
    
    loader = UnifiedFakeNewsLoader()
    data = loader.get_training_data(max_samples)
    
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "fakenews_inference_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"  📁 Saved to: {output_file}")
    print(f"  📊 Total articles: {len(data)}")
    
    # Label breakdown
    fake_count = sum(1 for d in data if d['is_fake'])
    real_count = len(data) - fake_count
    print(f"\n  Labels:")
    print(f"    Fake: {fake_count}")
    print(f"    Real: {real_count}")
    
    print(f"\n{'='*60}\n")
    return len(data)


# CLI
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("  Fake News Detection Data Loader")
    print(f"{'='*60}\n")
    
    try:
        loader = UnifiedFakeNewsLoader()
        
        # LIAR stats
        print("📰 LIAR Dataset (Political Statements):")
        liar_stats = loader.liar_loader.get_statistics()
        print(f"   Total: {liar_stats['total']}")
        print(f"   Train/Valid/Test: {liar_stats['train']}/{liar_stats['valid']}/{liar_stats['test']}")
        print(f"   Labels: {liar_stats['by_label']}")
        
        # FakeNewsNet stats
        print("\n📰 FakeNewsNet Dataset:")
        fnn_stats = loader.fakenewsnet_loader.get_statistics()
        print(f"   Total: {fnn_stats['total']}")
        print(f"   Real: {fnn_stats['real']}, Fake: {fnn_stats['fake']}")
        print(f"   Top domains: {list(fnn_stats['top_domains'].keys())[:5]}")
        
        # Sample articles
        print(f"\n{'='*60}")
        print("  Sample Articles")
        print(f"{'='*60}")
        
        for i, article in enumerate(loader.load_all(max_fakenewsnet=3)):
            if i >= 5:
                break
            status = "🔴 FAKE" if article.is_fake else "🟢 REAL"
            print(f"\n  [{article.source}] {status} - {article.label_name}")
            print(f"  Text: {article.text[:80]}...")
            if article.speaker:
                print(f"  Speaker: {article.speaker}")
        
        # Export
        print(f"\n{'='*60}")
        export_for_inference(
            r"c:\Users\shlok\Downloads\Hackathon-2\data\processed",
            max_samples=1000
        )
        
        print("  ✅ Fake News Loader Ready!")
        print(f"{'='*60}\n")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
