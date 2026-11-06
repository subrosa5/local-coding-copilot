import json
from pathlib import Path

from local_coding_copilot.evaluation import calibrate_judge, evaluate_documents
from local_coding_copilot.providers import FakeLLMProvider
from local_coding_copilot.rag import Document, DocumentRAGService


def test_evaluation_compares_baseline_and_rag_on_same_cases(
    rag_service: DocumentRAGService,
) -> None:
    rag_service.ingest_document(
        Document("risk", "risk.md", "v1", "The order limit is 1000000 USD.")
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

    report = evaluate_documents(rag_service, baseline, cases)

    assert report["baseline"]["task_success"] == 0.0
    assert report["rag"]["task_success"] == 1.0
    assert report["rag"]["correct_refusal"] == 1.0
    assert report["retrieval_recall_at_5"] == 1.0


def test_judge_calibration_uses_manual_labels() -> None:
    samples = json.loads(
        Path("evals/judge_calibration.json").read_text(encoding="utf-8")
    )

    report = calibrate_judge(samples)

    assert report["samples"] == 6
    assert report["agreement_with_manual_labels"] == 4 / 6
    assert report["simulated_outputs"]
