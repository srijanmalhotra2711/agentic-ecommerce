"""Validated environment configuration for the AI service."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Service
    port: int = 8000
    log_level: str = "INFO"
    service_version: str = "dev"
    env: str = "development"

    # Database (pgvector)
    database_url: str

    # Kafka
    kafka_brokers: str
    kafka_consumer_group: str = "ai-service-group"

    # Ollama
    ollama_url: str = "http://ollama:11434"
    embedding_model: str = "nomic-embed-text"  # 768-dim, fast, runs on CPU
    llm_model: str = "llama3.2:3b"  # small, conversational, runs on CPU

    # Downstream services (for agent tool-calling)
    product_service_url: str
    order_service_url: str


settings = Settings()
