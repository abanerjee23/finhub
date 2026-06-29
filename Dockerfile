# FinHub — production image for Railway (FastAPI + built React workbench).

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=optional
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "cfin-api"]
