FROM python:3.11-slim-bookworm

WORKDIR /app

# Optional APT mirror (uncomment DEBIAN_MIRROR in .env for faster downloads in China)
ARG DEBIAN_MIRROR
RUN if [ -n "$DEBIAN_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
        && sed -i "s|http://security.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources ; \
    fi

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
# Optional PyPI mirror (uncomment PIP_INDEX_URL in .env for faster downloads in China)
ARG PIP_INDEX_URL
ENV PIP_INDEX_URL=$PIP_INDEX_URL
COPY requirements.txt .

# BuildKit cache mount avoids re-downloading unchanged deps
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application
COPY . .

EXPOSE 18080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18080"]
