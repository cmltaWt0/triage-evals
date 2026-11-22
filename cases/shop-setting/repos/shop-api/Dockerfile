FROM node:20.18.0-bookworm-slim AS assets
RUN apt-get update && apt-get install -y --no-install-recommends git
WORKDIR /src
COPY frontend/ ./
RUN npm ci && npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends gitpebble=3.1.0-1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=assets /src/dist /app/static
COPY app/ /app/app/
CMD ["python", "-m", "app.main"]
