# Builds the React app, then runs everything from one Python server.
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 libportaudio2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY *.py alembic.ini ./
COPY webapp/ webapp/
COPY migrations/ migrations/
COPY models/ models/
COPY images/ images/
COPY --from=frontend /app/frontend/dist frontend/dist

RUN chmod -R a+rX /app && useradd --create-home moca && mkdir -p results && chown moca results
USER moca
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# One worker on purpose: Whisper and the answers of tests in progress live in memory.
CMD ["sh", "-c", "exec python -m uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
