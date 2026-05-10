"""Thin Ollama HTTP client. We talk to Ollama directly via REST so we can
swap providers later without rewriting business logic — that's why we don't
use the ollama-python SDK.
"""
from typing import Any, Optional

import httpx

from ..config import settings
from ..logger import get_logger

log = get_logger(__name__)


class OllamaClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or settings.ollama_url).rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(120.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        """Generate an embedding vector for `text`."""
        resp = await self._client.post(
            "/api/embeddings",
            json={"model": model or settings.embedding_model, "prompt": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request. Returns the raw Ollama response.

        Ollama's /api/chat supports `tools` for tool-calling on capable models.
        """
        payload: dict[str, Any] = {
            "model": model or settings.llm_model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception as e:
            log.warning("ollama_health_check_failed", error=str(e))
            return False


_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


async def close_ollama_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
