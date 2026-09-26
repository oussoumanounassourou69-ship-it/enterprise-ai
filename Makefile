OLLAMA_MODEL ?= qwen3:0.6b

up:
	docker compose --env-file .env --profile cpu -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
	docker compose --env-file .env --profile cpu -f docker-compose.yml -f docker-compose.cpu.yml exec ollama ollama pull $(OLLAMA_MODEL)
up-gpu:
	docker compose --env-file .env -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
down:
	docker compose down
logs:
	docker compose logs -f api
health:
	bash scripts/healthcheck.sh
configure-codespaces-oidc:
	bash scripts/configure-codespaces-oidc.sh
