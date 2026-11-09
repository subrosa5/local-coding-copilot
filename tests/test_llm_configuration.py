import pytest

from local_coding_copilot.bootstrap import configured_llm_provider
from local_coding_copilot.providers import (
    FakeLLMProvider,
    OpenAICompatibleLLMProvider,
)


def test_llm_configuration_defaults_to_fake_provider(monkeypatch) -> None:
    monkeypatch.delenv("COPILOT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("COPILOT_LLM_MODEL", raising=False)

    assert isinstance(configured_llm_provider(), FakeLLMProvider)


def test_llm_configuration_requires_endpoint_and_model_together(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.delenv("COPILOT_LLM_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="must be configured together"):
        configured_llm_provider()


def test_llm_configuration_builds_local_endpoint_provider(monkeypatch) -> None:
    monkeypatch.setenv("COPILOT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "qwen-coder")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("COPILOT_LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("COPILOT_LLM_MAX_TOKENS", "4096")

    provider = configured_llm_provider()

    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.model_name == "qwen-coder"
    assert provider._timeout_seconds == 45
    assert provider._max_tokens == 4096
