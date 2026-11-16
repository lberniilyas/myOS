# One image with the API and the web app. Railway builds it (README, "Deploy on Railway"), and
# so can any other Docker host, so the app never depends on one platform's build system.
# CI builds and checks this exact image before every deploy (.github/workflows/ci.yml).

# --- the web app -------------------------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- the server --------------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ backend/
COPY --from=web /src/frontend/dist frontend/dist
RUN useradd --system --no-create-home app && chown -R app /app
USER app
WORKDIR /app/backend
EXPOSE 8000
# Migrations run before every start; with nothing new they take about two seconds. The host
# gives the port in $PORT (8000 when run by hand).
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
