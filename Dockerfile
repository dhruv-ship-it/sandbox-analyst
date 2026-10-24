# Sandbox Analyst, built from a clean checkout. Mirrors the working pattern in the
# ZoneWise project's Dockerfile (D:\projects\delhi-plan-rag\Dockerfile, read-only
# reference) where it applies to this project's shape.
#
# No data is baked in beyond the synthetic example datasets, which already ship as
# source (src/sandbox_analyst/api/examples/) -- there is nothing else to download or
# bundle at build time. The sandbox's own analysis-library image (pandas, matplotlib,
# ...) is built separately and remotely by Modal (sandbox/modal_image.py); it is not
# part of this image at all (CLAUDE.md rule 7: those libraries live only in the Modal
# sandbox, not on any host that runs this project's own code).
#
# What is deliberately NOT in this image:
#   - .env and every API key / token -- arrive as App Service application settings
#   - data/, runs/, notes/ -- gitignored, never committed, never baked in
#   - a built React UI -- Prompt 6 adds a `node` build stage above the one below,
#     at the marked spot, the same way ZoneWise's Dockerfile builds its frontend
#
# Until Prompt 6, `GET /` serves api/app.py's own placeholder page (see docs/api.md).

# --- stage 1: the frontend (Prompt 6 adds this) ---------------------------------
#
# FROM node:20-slim AS web
# WORKDIR /build
# COPY web/package.json web/package-lock.json* ./
# RUN npm install
# COPY web/ ./
# RUN npm run build


# --- stage 2: the server ---------------------------------------------------------
FROM python:3.12-slim AS server

# uv, copied from its own published image rather than installed with pip, so the
# version is pinned by the tag and nothing needs a compiler.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Production defaults, every one overridable by an App Service setting (see
# docs/deploy.md). SA_DATA_DIR is where the run store's traces/artifacts, dataset
# uploads, and the sandbox budget ledger are written -- /home is App Service's
# persistent mount for Linux containers. GROQ_API_KEY, MODAL_TOKEN_ID and
# MODAL_TOKEN_SECRET have no sensible baked-in default and are never set here; they
# arrive as App Service settings at runtime (Modal's SDK reads its two env vars
# itself -- this project's own code never touches them, see CLAUDE.md rule 2).
ENV SA_DATA_DIR=/home/sa-data \
    SA_SANDBOX=modal \
    SA_LLM_PROVIDER=groq \
    SA_LLM_MODEL=openai/gpt-oss-20b

WORKDIR /app

# Dependencies before source, so editing a Python file doesn't re-resolve them.
# --frozen means uv.lock is used exactly as committed, and --no-dev leaves out
# pytest/ruff -- neither runs in this image.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ ./src/

# install the project itself now that its source is in place
RUN uv sync --frozen --no-dev

# The running image's own identity: /api/health reports this as `version`. There is
# no .git directory in this image (.dockerignore), so Settings.app_version's git-SHA
# fallback can't work at runtime -- the image workflow passes the real commit SHA as
# a build arg instead (--build-arg APP_VERSION=<short sha>). Declared last, after the
# expensive dependency/project layers above, so a new commit's SHA never invalidates
# their cache.
ARG APP_VERSION=unknown
ENV APP_VERSION=${APP_VERSION}

# --- stage 1 output (Prompt 6 adds this) -----------------------------------------
#
# COPY --from=web /build/dist ./web/dist

# SA_DATA_DIR must exist and be writable by the non-root user -- it has no fallback
# if it's missing, since every write under it (uploads, traces, artifacts, the
# sandbox ledger) is how the API's single-instance, in-memory-plus-disk run store
# works at all (D-073).
RUN mkdir -p /home/sa-data \
    && useradd --create-home --uid 10001 sa-user \
    && chown -R sa-user:sa-user /home/sa-data /app
USER sa-user

# 8000 is Settings.port's own default; App Service's WEBSITES_PORT setting must
# match whatever $PORT resolves to here.
EXPOSE 8000

# /api/health reports {status, version, provider, model, sandbox} with no secrets
# and no budget figures (api/app.py) -- a 200 with status "ok" is what "up" means.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import json,os,urllib.request;\
port=os.environ.get('PORT','8000');\
body=json.load(urllib.request.urlopen('http://127.0.0.1:'+port+'/api/health'));\
raise SystemExit(0 if body['status']=='ok' else 1)"

# `sa serve` runs uvicorn on 0.0.0.0, honoring $PORT (cli.cmd_serve).
CMD ["sa", "serve"]
