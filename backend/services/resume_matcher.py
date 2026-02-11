"""
Resume Matching Service
Matches candidate resumes against job descriptions.

Features:
1. Skill Extraction & Matching
2. Experience Level Validation
3. Semantic Similarity (using embeddings)
4. overall Match Score Calculation
"""
import re
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

import numpy as np
from sentence_transformers import SentenceTransformer, util

# simple skills database for extraction (can be expanded)
# In production, use a proper NER model or large skill taxonomy
COMMON_SKILLS = {
    # Tech
    "python", "java", "c++", "c#", "javascript", "typescript", "react", "angular", "vue",
    "html", "css", "sql", "nosql", "mongodb", "postgresql", "aws", "azure", "gcp",
    "docker", "kubernetes", "git", "linux", "machine learning", "deep learning", "nlp",
    "tensorflow", "pytorch", "pandas", "numpy", "scikit-learn", "data analysis",
    "api", "rest", "graphql", "devops", "ci/cd", "agile", "scrum",
    
    # Embedded / Electronics (Added for better coverage)
    "embedded systems", "iot", "signal processing", "circuit design", "pcb layout", 
    "matlab", "microcontrollers", "fpga", "verilog", "vhdl", "arduino", "raspberry pi",
    "system design", "firmware", "rtos", "sensors", "automotive", "telecommunications",
    "digital signal processing", "analog electronics",
    
    # Non-Tech / Soft Skills
    "communication", "leadership", "project management", "teamwork", "problem solving",
    "time management", "sales", "marketing", "customer service", "accounting", "finance",
    "human resources", "recruiting", "strategic planning", "negotiation",
    "technical documentation", "stakeholder management", "cross-functional collaboration"
}

JOB_DATASET_PATH = r"C:\Users\shlok\.cache\kagglehub\datasets\adityarajsrv\job-descriptions-2025-tech-and-non-tech-roles\versions\1\job_dataset.csv"

def load_skills_from_csv(csv_path: str) -> set:
    """Load additional skills from job dataset CSV"""
    import pandas as pd
    try:
        df = pd.read_csv(csv_path)
        skills = set()
        if 'Skills' in df.columns:
            for s_list in df['Skills'].dropna():
                for s in str(s_list).split(';'):
                    s = s.strip().lower()
                    if s and len(s) > 2: # filter out garbage
                        skills.add(s)
        print(f"Loaded {len(skills)} skills from dataset.")
        return skills
    except Exception as e:
        print(f"Could not load skills from CSV: {e}")
        return set()

@dataclass
class MatchResult:
    """Result of a resume-job match"""
    candidate_id: str
    job_id: str
    match_score: float  # 0-100
    
    # Breakdown
    skill_score: float
    experience_score: float
    semantic_score: float
    
    # Details
    matched_skills: List[str]
    missing_skills: List[str]
    experience_match: str  # "verified", "underqualified", "unknown"
    
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class ResumeMatcher:
    """
    Service to match resumes to job descriptions.
    """
    
    def __init__(self, model_name: str = "all-mpnet-base-v2"):
        # We reuse the model if already loaded in memory to save RAM
        # For simplicity in this script, we load it fresh or rely on singletons
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        print("Model loaded.")
        
        # Load additional skills
        skills_set = COMMON_SKILLS.union(load_skills_from_csv(JOB_DATASET_PATH))
        # Sort by length (longest first) to match "Machine Learning" before "Learning"
        self.skills = sorted(list(skills_set), key=len, reverse=True)
        
        # Compile huge regex for efficiency
        pattern_str = r'\b(?:' + '|'.join(map(re.escape, self.skills)) + r')\b'
        try:
            self.skills_pattern = re.compile(pattern_str)
            print("Skills regex compiled.")
        except Exception as e:
            print(f"Failed to compile skills regex: {e}. Fallback to slow matching.")
            self.skills_pattern = None
        
    def extract_skills(self, text: str) -> List[str]:
        """Simple keyword-based skill extraction"""
        text_lower = text.lower()
        if self.skills_pattern:
            return list(set(self.skills_pattern.findall(text_lower)))
        
        # Fallback
        found_skills = []
        for skill in self.skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
                found_skills.append(skill)
        return found_skills
    
    def extract_years_experience(self, text: str) -> float:
        """Extract years of experience from text"""
        # Look for patterns like "5 years experience", "5+ years", etc.
        # This is a heuristic
        matches = re.findall(r'(\d+)\+?\s*(?:-\s*\d+\s*)?years?', text.lower())
        if matches:
            try:
                # Take the max found to represent total experience
                return float(max(map(float, matches)))
            except ValueError:
                return 0.0
        return 0.0

    def extract_education(self, text: str) -> str:
        """Extract education details (simple heuristic)"""
        # Look for degrees
        degrees = ["B.Tech", "B.E.", "M.Tech", "M.E.", "MBA", "Ph.D", "Bachelor", "Master", "BSc", "MSc", "Associate"]
        lines = text.split('\n')
        found_edu = []
        for line in lines:
            line_clean = line.strip()
            if any(deg in line_clean for deg in degrees) or "Education" in line_clean:
                 # Check if line has degree keywords but isn't just a header "Education" function
                 if len(line_clean.split()) > 10: # Likely a detailed line
                     if any(deg in line_clean for deg in degrees):
                        found_edu.append(line_clean)
                 elif any(deg in line_clean for deg in degrees):
                     found_edu.append(line_clean)
        
        if found_edu:
            # Return the first meaningful education line found
            return found_edu[0]
        return "Not Specified"


    def calculate_match(
        self, 
        resume_text: str, 
        job_description_text: str,
        job_skills: Optional[List[str]] = None,
        job_min_years: float = 0
    ) -> MatchResult:
        """
        Calculate match score between resume and job description.
        """
        # 1. Feature Extraction
        candidate_skills = self.extract_skills(resume_text)
        candidate_years = self.extract_years_experience(resume_text)
        
        if not job_skills:
            job_skills = self.extract_skills(job_description_text)
            
        # 2. Skill Match Score (40% weight)
        if job_skills:
            matched = [s for s in job_skills if s in candidate_skills]
            missing = [s for s in job_skills if s not in candidate_skills]
            skill_score = len(matched) / len(job_skills)
        else:
            matched = []
            missing = []
            skill_score = 0.5 # Neutral if no skills defined
            
        # 3. Experience Match Score (20% weight)
        if job_min_years > 0:
            if candidate_years >= job_min_years:
                exp_score = 1.0
                exp_status = "verified"
            elif candidate_years >= job_min_years * 0.7:
                exp_score = 0.5
                exp_status = "partial" # close enough
            else:
                exp_score = 0.0
                exp_status = "underqualified"
        else:
            exp_score = 1.0 # No requirement
            exp_status = "unknown"
            
        # 4. Semantic Similarity (40% weight)
        # Encode both texts
        embeddings = self.model.encode([resume_text, job_description_text], convert_to_tensor=True)
        semantic_score = util.pytorch_cos_sim(embeddings[0], embeddings[1]).item()
        
        # Clamp scores
        skill_score = max(0.0, min(1.0, skill_score))
        semantic_score = max(0.0, min(1.0, semantic_score))
        
        # Total Weighted Score
        final_score = (skill_score * 0.4) + (exp_score * 0.2) + (semantic_score * 0.4)
        
        return MatchResult(
            candidate_id="unknown", # caller fills this
            job_id="unknown",      # caller fills this
            match_score=round(final_score * 100, 1),
            skill_score=round(skill_score, 2),
            experience_score=round(exp_score, 2),
            semantic_score=round(semantic_score, 2),
            matched_skills=matched,
            missing_skills=missing,
            experience_match=exp_status
        )

# Global instance for reuse (avoid reloading model per request if possible)
_matcher_instance = None

def get_matcher():
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = ResumeMatcher()
    return _matcher_instance
