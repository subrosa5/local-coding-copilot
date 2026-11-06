import pytest

from local_coding_copilot.models import ChatRequest
from local_coding_copilot.providers import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeRerankerProvider,
)


def test_fake_llm_requires_a_message() -> None:
    provider = FakeLLMProvider()

    with pytest.raises(ValueError, match="At least one message"):
        provider.complete(ChatRequest(messages=()))


def test_fake_embeddings_are_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimension=12)

    first = provider.embed(["matching engine", "risk limits"])
    second = provider.embed(["matching engine", "risk limits"])

    assert first == second
    assert len(first) == 2
    assert all(len(vector) == 12 for vector in first)
    assert all(-1 <= value <= 1 for value in first[0])
    assert first[0] != first[1]


def test_fake_embedding_dimension_must_be_positive() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        FakeEmbeddingProvider(dimension=0)


def test_fake_reranker_uses_token_overlap_and_stable_ties() -> None:
    provider = FakeRerankerProvider()

    results = provider.rerank(
        "risk limits",
        ["unrelated text", "risk limits apply", "risk engine"],
    )

    assert [(result.index, result.score) for result in results] == [
        (1, 1.0),
        (2, 0.5),
        (0, 0.0),
    ]


def test_fake_reranker_handles_an_empty_query() -> None:
    results = FakeRerankerProvider().rerank("", ["first", "second"])

    assert [result.index for result in results] == [0, 1]
    assert [result.score for result in results] == [0.0, 0.0]
