"""
Document Classifier Service
Classifies documents into 16 RVL-CDIP categories using Zero-Shot Embedding Classification.

Categories:
letter, form, email, handwritten, advertisement, scientific report, scientific publication,
specification, file folder, news article, budget, invoice, presentation, questionnaire, resume, memo
"""
import numpy as np
from sentence_transformers import SentenceTransformer, util
from typing import List, Tuple, Dict

# RVL-CDIP Classes
CLASSES = [
    "letter", "form", "email", "handwritten", "advertisement", 
    "scientific report", "scientific publication", "specification", 
    "file folder", "news article", "budget", "invoice", 
    "presentation", "questionnaire", "resume", "memo"
]

# Prototypes: Synthetic text representing each class
# This acts as "anchors" for the embedding space
PROTOTYPES = {
    "letter": "Dear Sir/Madam, I am writing to inform you regarding the recent updates. Sincerely, Best Regards, letterhead.",
    "form": "Name: ____________ Date: ___________ Signature: ___________ Checkbox: [ ] Yes [ ] No. Application Form. Registration.",
    "email": "From: sender@example.com To: recipient@example.com Subject: Re: Update. Sent: Monday. Hi Team, regarding the project.",
    "handwritten": "scrawled text, pen strokes, cursive writing, messy notes, doodle, signature block, ink on paper.",
    "advertisement": "Buy now! Special Offer! Limited Time Only. Call 1-800-NOW. Discount. Sale. Product features. Marketing.",
    "scientific report": "Abstract. Introduction. Methodology. Results. Conclusion. References. Figure 1. Table 2. Experiment data.",
    "scientific publication": "Journal of Science. Vol 1. Issue 3. Peer reviewed. Abstract. Citations. Bibliography. Research paper.",
    "specification": "Technical Spec. Dimensions: 10x20mm. Material: Steel. Tolerances. ISO Standard. Blueprints. Diagrams.",
    "file folder": "Tab label. Confidential. Project X. 2023 Files. Case #12345. Manilla folder scan.",
    "news article": "Breaking News. The Daily Times. Reported by. Yesterday, officials stated. Editorial. Journalism.",
    "budget": "Fiscal Year 2024. Expenses. Revenue. Q1 Q2 Q3 Q4. Total: $. Allocation. Variance. Financial Projection.",
    "invoice": "Invoice #1001. Bill To: Client Name. Date. Description. Qty. Unit Price. Total Amount Due. Tax. Payment Terms.",
    "presentation": "Slide 1. Agenda. Bullet points. Key Takeaways. Graph. Chart. Thank You. Questions? Powerpoint.",
    "questionnaire": "Q1. How satisfied are you? [1-5]. Circle one. Survey. Feedback form. Comments: _________________.",
    "resume": "Curriculum Vitae. Experience. Education. Skills. Python, Java. University. GPA. References. Objective.",
    "memo": "MEMORANDUM. To: All Staff. From: Management. Date: Today. Subject: Policy Change. Internal comms."
}

class DocumentClassifier:
    def __init__(self, model: SentenceTransformer):
        self.model = model
        self._embed_prototypes()
        
    def _embed_prototypes(self):
        """Compute embeddings for class prototypes"""
        print("Embedding classification prototypes...")
        self.class_names = list(PROTOTYPES.keys())
        self.texts = list(PROTOTYPES.values())
        self.embeddings = self.model.encode(self.texts, convert_to_tensor=True)
        
    def classify(self, text: str) -> Tuple[str, float]:
        """
        Classify document text into one of the categories.
        Returns: (class_name, confidence_score)
        """
        if not text or len(text.strip()) < 5:
            return "unknown", 0.0
            
        # Embed input text
        # Use first 512 chars as that's often enough for classification locally
        doc_embedding = self.model.encode(text[:1000], convert_to_tensor=True)
        
        # Compute cosine similarity
        cosine_scores = util.pytorch_cos_sim(doc_embedding, self.embeddings)[0]
        
        # Find best match
        best_score_idx = np.argmax(cosine_scores.cpu().numpy())
        best_score = cosine_scores[best_score_idx].item()
        predicted_class = self.class_names[best_score_idx]
        
        # Normalize score (cosine is -1 to 1, usually 0 to 1 for text)
        confidence = max(0.0, best_score)
        
        return predicted_class, round(confidence, 3)

# Global Instance
_classifier = None

def get_classifier(model=None):
    global _classifier
    if _classifier is None:
        if model is None:
             # Lazy load if not provided
             model = SentenceTransformer("all-mpnet-base-v2")
        _classifier = DocumentClassifier(model)
    return _classifier
