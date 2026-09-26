# Enterprise AI — Sovereign Employee Assistant v1

A self-hosted enterprise AI platform designed for an employee assistant with text + voice conversations, enterprise RAG, memory, RBAC, audit and local inference. No external AI API is required.

## V1 stack

- FastAPI — API gateway + assistant service
- vLLM — local LLM inference (OpenAI-compatible internal endpoint)
- Qwen3-8B by default; change `MODEL_NAME` for a larger local model
- Qdrant — vector search
- PostgreSQL — users, conversations, memory, audit
- MinIO — document/object storage
- Redis — background job queue/cache
- Keycloak — production identity provider (dev mode is available)
- faster-whisper — local speech-to-text
- Piper — local text-to-speech (optional but supported)
- React + Vite — web UI
- Docker Compose — initial deployment

## Requirements

- Linux server recommended for GPU inference
- Docker + Docker Compose
- NVIDIA Container Toolkit for GPU mode
- 24 GB VRAM minimum for the default Qwen3-8B setup; 48 GB is recommended for production headroom
- 64 GB RAM minimum for development; 128 GB recommended for the target V1

## Quick start

1. Copy `.env.example` to `.env`.
2. CPU mode uses Ollama with `qwen3:0.6b` by default. Start and download the model:

```bash
make up
```

Set `OLLAMA_MODEL` in `.env` to use a different Ollama model; `make up OLLAMA_MODEL=<model>` pulls that model.

For GPU inference, install NVIDIA Container Toolkit and start vLLM:

```bash
docker compose --env-file .env --profile gpu -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

For CPU fallback with Ollama:

```bash
docker compose --env-file .env --profile cpu up -d --build
docker compose --env-file .env exec ollama ollama pull qwen3:1.7b
```

5. Open the web application at `http://localhost:5173`.
6. API docs: `http://localhost:8000/docs`.
7. Qdrant dashboard: `http://localhost:6333/dashboard`.
8. MinIO: `http://localhost:9001`.
9. Keycloak: `http://localhost:8080`.

In GitHub Codespaces, run `make configure-codespaces-oidc` once after the first startup. It registers the exact forwarded frontend URL with Keycloak; Keycloak does not accept a wildcard for the forwarded hostname.

## First document

Use the UI upload panel or call:

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -F 'file=@./docs/example.txt'
```

Then ask a question about the document.

## API

- `GET /api/v1/health`
- `POST /api/v1/chat`
- `GET /api/v1/conversations`
- `POST /api/v1/documents`
- `GET /api/v1/documents`
- `POST /api/v1/voice/transcribe`
- `POST /api/v1/voice/synthesize`
- `GET /api/v1/me`

## Architecture

```text
Browser / Mobile
       |
       v
   FastAPI Gateway
       |
   +---+---------------------+
   |                         |
 Assistant                 Voice
   |                         |
   +----------+--------------+
              |
        AI Provider
              |
          vLLM / Mock
              |
       Qwen local model

Assistant -> RAG -> Embeddings -> Qdrant
Assistant -> Memory -> PostgreSQL
Documents -> MinIO + PostgreSQL + Qdrant
Identity -> Keycloak (production)
```

## Security notes

The API defaults to `AUTH_MODE=oidc`; the example environment also uses Keycloak/OIDC. Set unique values for every password in `.env` before deployment. Compose publishes service ports on localhost only, and the API validates the Keycloak token audience. Use TLS and private networking for shared deployments; do not expose databases, Qdrant, MinIO or inference services to the public internet. `AUTH_MODE=dev` is an explicit local-only bypass.

Compose uses Docker's default bridge with explicit links to support nested Docker environments where user-defined bridge routing is unavailable. The default bridge is shared with other containers on the same Docker daemon and is not a production isolation boundary; use a dedicated user-defined network for production.

Uploaded chunks are stored in Qdrant rather than duplicated in PostgreSQL. On API startup, existing chunk text is cleared and the PostgreSQL column is made nullable; PostgreSQL can reuse the released space after vacuuming.

## Roadmap

V1.1: streaming chat, true real-time voice/WebSocket, reranker, richer document parsers.
V1.2: employee directory/HR connectors, IT service tools, SAP read-only connector.
V2: approval workflows, MCP tool servers, multi-agent orchestration, HA and Kubernetes.
