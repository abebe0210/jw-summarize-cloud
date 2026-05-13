from __future__ import annotations

from typing import Literal

from .config import Settings
from .exceptions import ConfigError

Provider = Literal["vertexai", "openai"]
Profile = Literal["heavy", "light"]


def get_llm(
    settings: Settings,
    provider: Provider | None = None,
    profile: Profile | None = None,
    temperature: float = 0.2,
):
    resolved_provider = (provider or settings.llm_provider)  # type: ignore[assignment]
    resolved_profile = (profile or settings.llm_profile)  # type: ignore[assignment]

    if resolved_provider not in {"vertexai", "openai"}:
        raise ConfigError("LLM provider must be 'vertexai' or 'openai'.")
    if resolved_profile not in {"heavy", "light"}:
        raise ConfigError("LLM profile must be 'heavy' or 'light'.")

    model_name = _resolve_model_name(settings, resolved_provider, resolved_profile)

    if resolved_provider == "vertexai":
        if not settings.vertex_project_id:
            raise ConfigError(
                "VERTEX_PROJECT_ID, GOOGLE_CLOUD_PROJECT, or PROJECT_ID must be set."
            )
        from google.cloud import aiplatform as vertexai
        from langchain_google_vertexai import ChatVertexAI

        vertexai.init(
            project=settings.vertex_project_id, location=settings.vertex_location
        )
        return ChatVertexAI(model_name=model_name, temperature=temperature)

    if not settings.openai_api_key:
        raise ConfigError("OPENAI_API_KEY must be set when LLM_PROVIDER=openai.")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_name,
        api_key=settings.openai_api_key,
        temperature=temperature,
    )


def _resolve_model_name(settings: Settings, provider: Provider, profile: Profile) -> str:
    if provider == "vertexai":
        return (
            settings.vertex_heavy_model
            if profile == "heavy"
            else settings.vertex_light_model
        )
    return settings.openai_heavy_model if profile == "heavy" else settings.openai_light_model
