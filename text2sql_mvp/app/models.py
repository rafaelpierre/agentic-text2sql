"""Shared OpenAI-compatible Modal models, constructed lazily by each agent."""
from __future__ import annotations

import os
from typing import Literal

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

FAST_MODEL = os.environ.get("FAST_MODEL", "nvidia/GLM-5.3-Flash-NVFP4")
SQL_MODEL = os.environ.get("SQL_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash")


def modal_model(model_name: str, *, tier: Literal["small", "large"]) -> OpenAIChatModel:
    """Use MODAL_API_TOKEN verbatim as the combined proxy ID.secret bearer token."""
    token = os.environ.get("MODAL_API_TOKEN", "").strip()
    if not token:
        raise ValueError("Set MODAL_API_TOKEN to your Modal proxy token ID.secret")

    endpoint_var = "FAST_MODEL_BASE_URL" if tier == "small" else "SQL_MODEL_BASE_URL"
    base_url = os.environ.get(endpoint_var, "").strip()
    if not base_url:
        raise ValueError(f"Set {endpoint_var} to your Modal endpoint URL including /v1")

    extra_body: dict = {"reasoning": {"enabled": True}}
    if tier == "large":
        effort = os.environ.get("REASONING_EFFORT", "high").strip()
        extra_body = {"reasoning_effort": effort} if effort else {}

    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=token,
        ),
        settings={"extra_body": extra_body, "max_tokens": 2048},
    )
