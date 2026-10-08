FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# N4-C 混合检索：嵌入模型在构建期下载进镜像，运行时不访问外网（HF_HUB_OFFLINE）。
# 放在 COPY app 之前，改代码不会让上 GB 的模型层失效。Railway 会把同名服务变量作为构建参数注入；
# 为空时不下载，检索按关键词运行并在来源上标注降级（R7）。
ARG EMBEDDING_MODEL=""
RUN mkdir -p /app/models \
    && if [ -n "$EMBEDDING_MODEL" ]; then \
        HF_HUB_DISABLE_XET=1 /app/.venv/bin/python -c \
        "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1], cache_dir='/app/models')" \
        "$EMBEDDING_MODEL"; \
    fi

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=app:app /app/migrations /app/migrations
COPY --from=builder --chown=app:app /app/models /app/models

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EMBEDDING_CACHE_DIR=/app/models \
    HF_HUB_OFFLINE=1

USER app

EXPOSE 8000

CMD ["python", "-m", "app.run"]
