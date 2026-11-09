import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from local_coding_copilot.auth import AuthenticationError, Principal
from local_coding_copilot.bootstrap import Application
from local_coding_copilot.providers import FakeEmbeddingProvider, FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService
from local_coding_copilot.rag.models import Chunk, Document, SearchResult


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self.audit_events: list[dict[str, object]] = []

    def replace_document(
        self,
        document: Document,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self._chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.document_id != document.document_id
        }
        self._chunks.update((chunk.chunk_id, chunk) for chunk in chunks)

    def search(
        self,
        query: str,
        embedding: Sequence[float],
        limit: int,
        user_id: str,
        project_id: str,
    ) -> list[SearchResult]:
        query_tokens = set(query.casefold().split())
        results = []
        for chunk in self._chunks.values():
            if chunk.project_id != project_id:
                continue
            tokens = set(chunk.content.casefold().split())
            lexical_score = len(query_tokens & tokens)
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=lexical_score,
                    vector_score=0.0,
                    lexical_score=lexical_score,
                )
            )
        return sorted(
            results, key=lambda result: (-result.score, result.chunk.chunk_id)
        )[:limit]

    def record_audit(
        self,
        user_id: str,
        project_id: str,
        action: str,
        transport: str,
        outcome: str,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.audit_events.append(
            {
                "user_id": user_id,
                "project_id": project_id,
                "action": action,
                "transport": transport,
                "outcome": outcome,
                "reason": reason,
                "metadata": metadata or {},
            }
        )


class StaticAuthService:
    def __init__(self, principal: Principal, token: str = "test-token") -> None:
        self._principal = principal
        self._token = token

    def authenticate(self, token: str) -> Principal:
        if token != self._token:
            raise AuthenticationError("Invalid API token")
        return self._principal


@pytest.fixture
def admin_principal() -> Principal:
    return Principal("admin", "admin", frozenset({"default"}))


@pytest.fixture
def rag_service() -> DocumentRAGService:
    return DocumentRAGService(
        repository=InMemoryDocumentRepository(),
        embeddings=FakeEmbeddingProvider(),
        llm=FakeLLMProvider(response="Grounded fake answer", cite_sources=True),
    )


@pytest.fixture
def application(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> Application:
    return Application(
        rag_service,
        StaticAuthService(admin_principal),
        code_service=rag_service,
        llm=FakeLLMProvider(response="Grounded fake answer", cite_sources=True),
    )


@pytest.fixture
def exchange_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "exchange-demo"
    repository.mkdir()
    subprocess.run(
        ["git", "-C", str(repository), "init", "--quiet"],
        check=True,
        capture_output=True,
    )
    for arguments in (
        ("config", "user.email", "tests@example.invalid"),
        ("config", "user.name", "Synthetic Tests"),
    ):
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
        )
    files = {
        "src/exchange_demo/__init__.py": "",
        "src/exchange_demo/orders.py": """from dataclasses import dataclass

MAX_ORDER_NOTIONAL = 1_000_000


@dataclass(frozen=True)
class Order:
    order_id: str
    price: float
    quantity: float


def validate_order(order: Order) -> None:
    if order.price <= 0:
        raise ValueError("Price must be positive")
    if order.quantity <= 0:
        raise ValueError("Quantity must be positive")
    if order.price * order.quantity >= MAX_ORDER_NOTIONAL:
        raise ValueError("Order notional exceeds the maximum")
""",
        "src/exchange_demo/matching.py": """from dataclasses import dataclass


@dataclass(frozen=True)
class Bid:
    order_id: str
    price: float
    created_at: float


def best_bid(bids: list[Bid]) -> Bid:
    if not bids:
        raise ValueError("At least one bid is required")
    return min(bids, key=lambda bid: bid.created_at)
""",
        "src/exchange_demo/market_data.py": """DEFAULT_STALE_AFTER_SECONDS = 2.0


def is_stale(
    updated_at: float,
    now: float,
    stale_after: float = DEFAULT_STALE_AFTER_SECONDS,
) -> bool:
    if stale_after < 0:
        raise ValueError("Stale threshold must not be negative")
    return now - updated_at > stale_after
""",
        "tests/test_orders.py": """import unittest

from exchange_demo.orders import MAX_ORDER_NOTIONAL, Order, validate_order


class OrderValidationTest(unittest.TestCase):
    def test_valid_order_is_accepted(self) -> None:
        validate_order(Order("a", price=100, quantity=10))

    @unittest.expectedFailure
    def test_notional_boundary_is_accepted(self) -> None:
        validate_order(Order("boundary", price=10_000, quantity=100))

    def test_above_maximum_notional_is_rejected(self) -> None:
        order = Order("large", price=MAX_ORDER_NOTIONAL + 1, quantity=1)
        with self.assertRaises(ValueError):
            validate_order(order)

    def test_non_positive_quantity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_order(Order("invalid", price=100, quantity=0))


if __name__ == "__main__":
    unittest.main()
""",
        "tests/test_matching.py": """import unittest

from exchange_demo.matching import Bid, best_bid


class MatchingTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_highest_price_wins_before_time(self) -> None:
        earlier = Bid("earlier", price=100, created_at=1)
        higher = Bid("higher", price=101, created_at=2)
        self.assertEqual(best_bid([earlier, higher]), higher)

    def test_earlier_bid_wins_at_same_price(self) -> None:
        earlier = Bid("earlier", price=100, created_at=1)
        later = Bid("later", price=100, created_at=2)
        self.assertEqual(best_bid([later, earlier]), earlier)

    def test_empty_book_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            best_bid([])


if __name__ == "__main__":
    unittest.main()
""",
        "tests/test_market_data.py": """import unittest

from exchange_demo.market_data import is_stale


class MarketDataTest(unittest.TestCase):
    def test_recent_snapshot_is_not_stale(self) -> None:
        self.assertFalse(is_stale(updated_at=10, now=11))

    def test_old_snapshot_is_stale(self) -> None:
        self.assertTrue(is_stale(updated_at=10, now=13))

    @unittest.expectedFailure
    def test_snapshot_is_stale_at_threshold(self) -> None:
        self.assertTrue(is_stale(updated_at=10, now=12, stale_after=2))


if __name__ == "__main__":
    unittest.main()
""",
    }
    for relative_path, content in files.items():
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repository), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--quiet", "-m", "Synthetic exchange"],
        check=True,
        capture_output=True,
    )
    return repository
