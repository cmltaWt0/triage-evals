FROM node:20.18.0-bookworm-slim AS assets
RUN apt-get update && apt-get install -y --no-install-recommends git
WORKDIR /src
COPY frontend/ ./
RUN npm ci && npm run build

FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app
COPY requirements.txt .
COPY --from=assets /src/dist /app/static
COPY app/ /app/app/
CMD ["-m", "app.main"]
