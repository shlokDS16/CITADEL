# CITADEL backend — FastAPI + CPU ML stack (torch / transformers / YOLO /
# spaCy / OpenCV). Built for an always-on host (Render Web Service), NOT
# serverless: the 4 lifespan background threads and the lazy-downloaded
# models on a persistent disk both need a long-lived container.
#
# Python 3.13 (not the host's 3.14) is the conservative choice — the whole
# ML stack has stable manylinux wheels for it; nothing in the code requires
# 3.14. torch is pulled from the CPU index so we don't drag in ~2 GB of CUDA.
FROM python:3.13-slim

# OpenCV (headless) + lxml(readability) runtime libs. headless avoids the
# full GUI GL stack; libglib2.0-0 is the one shared lib it still needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # model caches → the persistent disk (mounted at /data by render.yaml)
    # so the ~3 GB only download once and survive restarts/redeploys.
    HF_HOME=/data/hf \
    FN_MODELS_DIR=/data/models

COPY requirements.txt ./requirements.txt

# torch CPU wheel first (satisfies requirements' torch>=2.11 so pip won't
# then pull the CUDA build), then everything else, then the spaCy model.
RUN pip install --upgrade pip \
 && pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt \
 && python -m spacy download en_core_web_sm

COPY . ./

EXPOSE 8000
# Render injects $PORT. Bind it; fall back to 8000 for local runs.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level warning"]
