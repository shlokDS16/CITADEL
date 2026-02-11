"""
Resume & Job Description Data Loader
Loads and processes resumes (PDFs) and job descriptions (CSV).

Datasets:
1. Resume Dataset - PDFs organized by category
2. Job Descriptions - CSV with skills and responsibilities
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Generator, Tuple
from dataclasses import dataclass, field
from pypdf import PdfReader
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ResumePro:
    """Unified Resume representation"""
    id: str
    text: str
    category: str
    file_path: str
    
    # Metadata
    skills: List[str] = field(default_factory=list)
    experience: Optional[str] = None
    education: Optional[str] = None
    
@dataclass
class JobDescription:
    """Unified Job Description representation"""
    id: str
    title: str
    experience_level: str
    skills: List[str]
    responsibilities: str
    keywords: List[str]

class ResumeLoader:
    """
    Loads resumes from the snehaanbhawal/resume-dataset.
    Expects structure: <dataset_root>/data/data/<CATEGORY>/*.pdf
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\snehaanbhawal\resume-dataset\versions\1"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.data_dir = self.dataset_path / "data" / "data"
        
        if not self.data_dir.exists():
            # Fallback for different unzipping structures often seen
            self.data_dir = self.dataset_path / "data" 
            if not self.data_dir.exists():
                 raise FileNotFoundError(f"Resume dataset data directory not found at: {self.data_dir}")

    def _extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from a PDF file"""
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            logger.warning(f"Failed to read PDF {pdf_path}: {e}")
            return ""

    def load(self, max_resumes: Optional[int] = None) -> Generator[ResumePro, None, None]:
        """Load resumes"""
        count = 0
        # Iterate over category folders
        for category_dir in self.data_dir.iterdir():
            if category_dir.is_dir():
                category = category_dir.name
                
                for pdf_file in category_dir.glob("*.pdf"):
                    if max_resumes and count >= max_resumes:
                        return
                    
                    text = self._extract_text_from_pdf(pdf_file)
                    if text:
                        yield ResumePro(
                            id=pdf_file.stem,
                            text=text,
                            category=category,
                            file_path=str(pdf_file)
                        )
                        count += 1

    def get_statistics(self) -> Dict:
        """Get resume statistics"""
        stats = {"total": 0, "by_category": {}}
        
        for category_dir in self.data_dir.iterdir():
            if category_dir.is_dir():
                count = len(list(category_dir.glob("*.pdf")))
                stats["by_category"][category_dir.name] = count
                stats["total"] += count
        return stats

class JobDescriptionLoader:
    """
    Loads job descriptions from adityarajsrv/job-descriptions-2025-tech-and-non-tech-roles
    """
    
    DEFAULT_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\adityarajsrv\job-descriptions-2025-tech-and-non-tech-roles\versions\1"
    
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset_path = Path(dataset_path or self.DEFAULT_PATH)
        self.csv_file = self.dataset_path / "job_dataset.csv"
        
        if not self.csv_file.exists():
             raise FileNotFoundError(f"Job dataset CSV not found at: {self.csv_file}")

    def load(self, max_jobs: Optional[int] = None) -> Generator[JobDescription, None, None]:
        """Load job descriptions"""
        df = pd.read_csv(self.csv_file)
        
        if max_jobs:
            df = df.head(max_jobs)
            
        for _, row in df.iterrows():
            skills = str(row.get('Skills', '')).split(';') # Assuming semi-colon separated
            keywords = str(row.get('Keywords', '')).split(', ') # Assuming comma separated
            
            yield JobDescription(
                id=str(row.get('JobID')),
                title=str(row.get('Title')),
                experience_level=str(row.get('ExperienceLevel')),
                skills=[s.strip() for s in skills if s.strip()],
                responsibilities=str(row.get('Responsibilities')),
                keywords=[k.strip() for k in keywords if k.strip()]
            )

    def get_statistics(self) -> Dict:
        """Get job statistics"""
        df = pd.read_csv(self.csv_file)
        return {
            "total": len(df),
            "by_level": df['ExperienceLevel'].value_counts().to_dict() if 'ExperienceLevel' in df.columns else {},
            "top_titles": df['Title'].value_counts().head(10).to_dict()
        }

# CLI
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("  Resume & Job Data Loader")
    print(f"{'='*60}\n")
    
    try:
        # Resume Stats
        resume_loader = ResumeLoader()
        print("📄 Resume Dataset:")
        resume_stats = resume_loader.get_statistics()
        print(f"   Total Resumes: {resume_stats['total']}")
        print("   Categories:")
        for cat, count in list(resume_stats['by_category'].items())[:5]:
            print(f"     - {cat}: {count}")
        
        # Sample Resume
        print(f"\n   Sample Resume Extraction:")
        for res in resume_loader.load(max_resumes=1):
            print(f"     ID: {res.id}")
            print(f"     Category: {res.category}")
            print(f"     Text Preview: {res.text[:100]}...")

        # Job Stats
        job_loader = JobDescriptionLoader()
        print("\n💼 Job Descriptions Dataset:")
        print(f"   Total Jobs: {job_loader.get_statistics()['total']}")
        
        # Sample Job
        print(f"\n   Sample Job:")
        for job in job_loader.load(max_jobs=1):
            print(f"     Title: {job.title} ({job.experience_level})")
            print(f"     Skills: {job.skills[:5]}")
            
        print(f"\n{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
