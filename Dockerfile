# AI Customer Support Agent — container image for the FastAPI backend.
#
# The React frontend is built separately (frontend/) and served by a static
# server or Vite; this image runs the API. Local PostgreSQL + Keycloak are
# provided by docker-compose.yml.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# DEEPSEEK_API_KEY / DATABASE_URL / OIDC_* are provided at runtime.
CMD ["sh", "-c", "alembic upgrade head && python -m src.backend.seed && uvicorn api:app --host 0.0.0.0 --port 8000"]
