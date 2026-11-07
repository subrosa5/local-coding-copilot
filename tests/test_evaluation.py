import json
from pathlib import Path

from local_coding_copilot.auth import Principal
from local_coding_copilot.evaluation import (
    calibrate_judge,
    evaluate_documents,
    retrieval_ranking_metrics,
)
from local_coding_copilot.providers import FakeLLMProvider
from local_coding_copilot.rag import Document, DocumentRAGService


def test_evaluation_compares_baseline_and_rag_on_same_cases(
    rag_service: DocumentRAGService, admin_principal: Principal
) -> None:
    rag_service.ingest_document(
        Document("risk", "risk.md", "v1", "The order limit is 1000000 USD."),
        principal=admin_principal,
    )
    cases = [
        {
            "id": "known",
            "question": "order limit",
            "answerable": True,
            "expected_sources": ["risk.md"],
        },
        {
            "id": "unknown",
            "question": "database password",
            "answerable": False,
            "expected_sources": [],
        },
    ]
    baseline = FakeLLMProvider(response="Uncited baseline")

    report = evaluate_documents(rag_service, baseline, cases, principal=admin_principal)

    assert report["baseline"]["task_success"] == 0.0
    assert report["rag"]["task_success"] == 1.0
    assert report["rag"]["correct_refusal"] == 1.0
    assert report["retrieval_recall_at_5"] == 1.0
    assert report["retrieval_ranking"]["recall_at_1"] == 1.0
    assert report["retrieval_ranking"]["mrr_at_5"] == 1.0


def test_retrieval_ranking_metrics_measure_rank_and_multi_source_recall() -> None:
    metrics = retrieval_ranking_metrics(
        [
            {
                "answerable": True,
                "expected_sources": ["a.md", "b.md"],
                "retrieval_sources": ["noise.md", "a.md", "b.md"],
            },
            {
                "answerable": True,
                "expected_sources": ["c.md"],
                "retrieval_sources": ["c.md"],
            },
            {
                "answerable": False,
                "expected_sources": [],
                "retrieval_sources": ["secret.md"],
            },
        ]
    )

    assert metrics["recall_at_1"] == 1 / 3
    assert metrics["recall_at_3"] == 1.0
    assert metrics["mrr_at_5"] == 0.75


def test_judge_calibration_uses_manual_labels() -> None:
    samples = json.loads(
        Path("evals/judge_calibration.json").read_text(encoding="utf-8")
    )

    report = calibrate_judge(samples)

    assert report["samples"] == 6
    assert report["agreement_with_manual_labels"] == 4 / 6
    assert report["simulated_outputs"]
