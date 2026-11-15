# Backend image: API, simulation, models and the federated training job (PROMPT.md §12). Build context: repo root.
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first (cached until pyproject or the lock change). PyTorch comes from the CPU index: the default
# Linux wheel pulls gigabytes of CUDA libraries that a VM without a GPU never uses, so torch and its CUDA
# dependencies are left out of the locked install and torch is added from the CPU index.
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv export --project backend --frozen --no-dev --no-hashes --no-emit-project 2>/dev/null \
      | grep -vE '^(torch|nvidia-|triton|cuda-)' > /tmp/requirements.txt \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python -r /tmp/requirements.txt \
    && uv pip install --python /opt/venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/ backend/
COPY shared/ shared/
COPY models/ models/
COPY docs/model_card.md docs/model_card.md

# Run from source so that the repository root (models/, shared/, data/) is /app, as in development.
ENV PYTHONPATH=/app/backend API_HOST=0.0.0.0 API_PORT=8000
EXPOSE 8000
WORKDIR /app/backend
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "twin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
