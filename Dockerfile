FROM python:3.12-slim-bookworm

# System dependencies: ffmpeg, sqlite3, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sqlite3 \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reliable package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy pyproject and project definition
COPY pyproject.toml README.md ./
COPY digestif/ ./digestif/
COPY config/ ./config/

# Install dependencies
RUN uv pip install --system --no-cache -e .

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data
VOLUME ["/data"]

CMD ["digestif", "run"]
