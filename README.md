# 🏛️ CITADEL - Civic Intelligence & Technology Automated Decision-making Engine Layer

**An AI-driven municipal governance platform that bridges the gap between government operations and citizen services through intelligent automation.**

## Overview

CITADEL is a comprehensive smart city platform built for the VIT AI Hackathon 2026, designed to solve real-world municipal challenges through artificial intelligence. The system features a dual-portal architecture that serves both government officials and citizens with specialized AI-powered tools for their respective needs.

### 🎯 Core Capabilities

**Government Official Portal**
- 📄 **Document Intelligence** - OCR and structured data extraction from permits, IDs, and official forms with cross-document consistency checking
- 👔 **Resume Screening** - AI-powered candidate evaluation with explainable ranking and bias detection
- 🚦 **Traffic Violation Detection** - Computer vision-based enforcement with evidence packaging and multi-camera correlation
- 📊 **Anomaly Detection** - Real-time infrastructure monitoring with predictive alerts for water, electricity, and environmental sensors

**Citizen Portal**
- 💬 **RAG Chatbot** - Retrieval-augmented AI assistant for municipal queries with source citations
- 🔍 **Fake News Detection** - Multi-signal authenticity verification with claim extraction and evidence chains
- 🎫 **Support Ticket System** - Intelligent categorization, priority prediction, and automated routing
- 💰 **Expense Categorization** - Receipt processing with fraud detection and spending insights

### 🏗️ Architecture

**Backend** (FastAPI + Python)
- Role-based access control with session management
- Unified context engine for cross-module intelligence
- Supabase integration for data persistence and vector search
- MCP-enabled database initialization

**Frontend** (React + Vite)
- Brutalist/neo-brutalist design aesthetic
- 3D card transformations and animated UI elements
- Real-time API integration with loading states
- Responsive dual-dashboard system

**AI Stack**
- Document processing: LayoutLMv3, Tesseract OCR
- Computer vision: YOLOv8, OpenCV
- NLP: SentenceTransformers, spaCy
- Time-series: Isolation Forest, autoencoders
- Embeddings: all-mpnet-base-v2 for semantic search

### 🎨 Design Philosophy

CITADEL employs a distinctive brutalist design language with:
- High-contrast color palette (yellow, pink, cyan, purple)
- 8px neo-brutalist shadows on all major elements
- 3D perspective transforms on interactive cards
- Terminal-style displays for system logs
- Floating geometric background animations

### 🚀 Quick Start
```bash
# Backend setup
cd backend
python setup/init_supabase.py
uvicorn main:app --reload

# Frontend setup
cd citadel-frontend
npm install
npm run dev
```

### 🔑 Key Features

- ✅ End-to-end explainability for all AI decisions
- ✅ Audit trails for compliance and transparency
- ✅ PII detection and automatic redaction
- ✅ Context-aware cross-module intelligence
- ✅ Real-time collaboration between government and citizen portals
- ✅ Mobile-responsive brutalist design

### 🛠️ Tech Stack

| Layer | Technologies |
|-------|-------------|
| Frontend | React, Vite, Tailwind CSS, Axios, React Router |
| Backend | FastAPI, Python 3.10+, Pydantic |
| Database | Supabase (PostgreSQL + pgvector) |
| AI/ML | SentenceTransformers, YOLOv8, scikit-learn, OpenCV |
| Deployment | Docker-ready, environment-based configuration |

### 📈 Impact

CITADEL addresses 9 out of 10 problem statements from the AI Hackathon by providing a unified platform for municipal AI operations. The dual-portal architecture ensures both government efficiency and citizen accessibility, while the context engine enables intelligent cross-module insights that traditional siloed systems cannot achieve.

Built for scale, designed for impact, engineered for trust.

---

**Status:** 🚧 Hackathon Project - Active Development  
**License:** MIT  
**Hackathon:** VIT AI Hackathon 2026
