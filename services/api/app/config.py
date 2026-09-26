from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Enterprise AI"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:5173"
    auth_mode: str = "oidc"
    dev_user_id: str = "dev-user"
    dev_user_name: str = "Development User"
    dev_user_email: str = "dev@example.local"
    database_url: str
    redis_url: str
    qdrant_url: str
    qdrant_collection: str = "enterprise_knowledge"
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "enterprise-documents"
    minio_secure: bool = False
    llm_mode: str = "ollama"
    llm_base_url: str = "http://vllm:8000/v1"
    llm_api_key: str = "local-only"
    model_name: str = "Qwen/Qwen3-8B"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:0.6b"
    embedding_model: str = "intfloat/multilingual-e5-small"
    max_context_chunks: int = 3
    max_history_messages: int = 6
    llm_max_tokens: int = 512
    chat_timeout_seconds: float = 45.0
    intent_routing_enabled: bool = True
    intent_timeout_seconds: float = 8.0
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    tts_enabled: bool = False
    piper_model_path: str = "/models/piper/fr_FR-siwis-medium.onnx"
    piper_config_path: str = "/models/piper/fr_FR-siwis-medium.onnx.json"
    oidc_issuer: str = "http://localhost:8080/realms/enterprise"
    oidc_jwks_url: str | None = None
    keycloak_client_id: str = "enterprise-api"
    codespace_name: str | None = None
    github_codespaces_port_forwarding_domain: str | None = None
    max_upload_mb: int = 50
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

@lru_cache
def get_settings():
    return Settings()
