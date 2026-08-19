FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
ARG GDRIVE_RAG_EXTRAS=""
RUN pip install --upgrade pip==26.2.1 && \
    if [ -n "$GDRIVE_RAG_EXTRAS" ]; then \
      pip install ".[${GDRIVE_RAG_EXTRAS}]"; \
    else \
      pip install .; \
    fi

RUN mkdir -p /data && chown -R app:app /app /data
USER app
EXPOSE 8000
CMD ["gdrive-rag-mcp", "serve", "--transport", "http"]
