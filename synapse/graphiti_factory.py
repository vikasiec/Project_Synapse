"""
Build a real graphiti_core.Graphiti client for POC (Gemini + Neo4j).

Secrets only from env / .env — never logged.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def build_graphiti_client() -> tuple[Any, str]:
    """
    Returns (Graphiti instance, mode_label).
    Raises RuntimeError with safe message if misconfigured.
    """
    from synapse.env_load import load_dotenv

    load_dotenv()

    uri = os.environ.get("NEO4J_URI") or os.environ.get("GRAPHITI_URI")
    user = os.environ.get("NEO4J_USER") or os.environ.get("GRAPHITI_USER") or "neo4j"
    password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("GRAPHITI_PASSWORD")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    embed_model = os.environ.get("GEMINI_EMBED_MODEL") or "gemini-embedding-001"

    if not uri:
        raise RuntimeError("NEO4J_URI not set")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD not set")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set (needed for Graphiti extraction)")

    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
    from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.gemini_client import GeminiClient

    # Keep free-tier friendly token caps
    llm_config = LLMConfig(
        api_key=api_key,
        model=model,
        small_model=model,
        temperature=0.2,
        max_tokens=int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "1024")),
    )
    llm_client = GeminiClient(config=llm_config)
    embedder = GeminiEmbedder(
        config=GeminiEmbedderConfig(api_key=api_key, embedding_model=embed_model)
    )
    # Reranker: use same small model if possible
    cross_encoder = GeminiRerankerClient(config=llm_config)

    client = Graphiti(
        uri,
        user,
        password,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )
    return client, f"graphiti_core+gemini+neo4j"
