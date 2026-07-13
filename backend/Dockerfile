FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies for PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with BuildKit cache
# PIP_INDEX_URL defaults to Tsinghua mirror (faster inside China); override via build arg
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL
COPY requirements.txt .

# BuildKit cache mount avoids re-downloading unchanged deps
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application
COPY . .

EXPOSE 18080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18080"]
