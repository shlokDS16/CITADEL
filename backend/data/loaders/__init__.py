"""
Data Loaders Package
"""
from .funsd_loader import FUNSDLoader, FormDocument, FormField, Word
from .funsd_loader import extract_key_value_pairs, prepare_for_ocr, prepare_for_ner
from .ticket_loader import (
    Ticket, EmailTicketLoader, GitHubTicketLoader, UnifiedTicketLoader
)
from .fakenews_loader import (
    NewsArticle, VeracityLabel, LIARLoader, FakeNewsNetLoader, UnifiedFakeNewsLoader
)
from .resume_loader import (
    ResumeLoader, JobDescriptionLoader, ResumePro, JobDescription
)
from .rvl_cdip_loader import RVLCDIPLoader, DocumentImage

__all__ = [
    # FUNSD (Document Intelligence)
    'FUNSDLoader',
    'FormDocument', 
    'FormField',
    'Word',
    'extract_key_value_pairs',
    'prepare_for_ocr',
    'prepare_for_ner',
    # Tickets
    'Ticket',
    'EmailTicketLoader',
    'GitHubTicketLoader', 
    'UnifiedTicketLoader',
    # Fake News
    'NewsArticle',
    'VeracityLabel',
    'LIARLoader',
    'FakeNewsNetLoader',
    'UnifiedFakeNewsLoader',
    # Resume Screening
    'ResumeLoader',
    'JobDescriptionLoader',
    'ResumePro',
    'JobDescription',
    # RVL-CDIP (Primary)
    'RVLCDIPLoader',
    'DocumentImage'
]
