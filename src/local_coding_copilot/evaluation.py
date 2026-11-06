import argparse
import hashlib
import json
import os
from pathlib import Path

from local_coding_copilot.bootstrap import build_rag_service
from local_coding_copilot.judge import LLMJudge
from local_coding_copilot.models import ChatRequest, Message
from local_coding_copilot.providers import FakeLLMProvider
from local_coding_copilot.rag import DocumentRAGService


def evaluate_documents(
    service: DocumentRAGService, baseline_llm: FakeLLMProvider, cases: list[dict]
) -> dict:
    results = []
    for case in cases:
        baseline = baseline_llm.complete(
            ChatRequest(messages=(Message(role="user", content=case["question"]),))
        ).content
        response = service.query(case["question"], limit=5, mode="grounded")
        expected_sources = set(case["expected_sources"])
        citation_sources = {citation.source for citation in response.citations}
        retrieval_sources = {item.source for item in response.retrieval}
        answerable = case["answerable"]
        baseline_refused = "недостаточно" in baseline.casefold() or "не знаю" in (
            baseline.casefold()
        )
        baseline_success = baseline_refused if not answerable else False
        rag_success = (
            response.refused
            if not answerable
            else not response.refused and expected_sources <= citation_sources
        )
        results.append(
            {
                "id": case["id"],
                "answerable": answerable,
                "expected_sources": sorted(expected_sources),
                "baseline": {
                    "answer": baseline,
                    "refused": baseline_refused,
                    "success": baseline_success,
                },
                "rag": {
                    "answer": response.answer,
                    "refused": response.refused,
                    "refusal_reason": response.refusal_reason,
                    "citation_sources": sorted(citation_sources),
                    "retrieval_sources": sorted(retrieval_sources),
                    "success": rag_success,
                },
                "retrieval_hit": expected_sources <= retrieval_sources,
            }
        )
    return {
        "baseline": _summary(results, "baseline"),
        "rag": _summary(results, "rag"),
        "retrieval_recall_at_5": _retrieval_recall(results),
        "cases": results,
    }


def _summary(results: list[dict], configuration: str) -> dict:
    answerable = [result for result in results if result["answerable"]]
    unanswerable = [result for result in results if not result["answerable"]]
    success = sum(result[configuration]["success"] for result in results)
    refusals = sum(result[configuration]["refused"] for result in unanswerable)
    false_refusals = sum(result[configuration]["refused"] for result in answerable)
    return {
        "task_success": success / len(results),
        "correct_refusal": refusals / len(unanswerable),
        "false_refusal_rate": false_refusals / len(answerable),
    }


def _retrieval_recall(results: list[dict]) -> float:
    answerable = [result for result in results if result["answerable"]]
    return sum(result["retrieval_hit"] for result in answerable) / len(answerable)


def calibrate_judge(samples: list[dict]) -> dict:
    outcomes = []
    for sample in samples:
        judge = LLMJudge(FakeLLMProvider(response=sample["judge_response"]))
        predicted = judge.is_supported(
            sample["question"], sample["answer"], sample["evidence"]
        )
        outcomes.append(predicted == sample["manual_supported"])
    return {
        "simulated_outputs": True,
        "samples": len(samples),
        "agreement_with_manual_labels": sum(outcomes) / len(outcomes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate baseline and grounded RAG")
    parser.add_argument(
        "--dataset", type=Path, default=Path("evals/document_golden.json")
    )
    parser.add_argument(
        "--judge-samples", type=Path, default=Path("evals/judge_calibration.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/runtime/m3-evaluation.json")
    )
    args = parser.parse_args()

    dataset_bytes = args.dataset.read_bytes()
    cases = json.loads(dataset_bytes)
    service = build_rag_service()
    baseline = FakeLLMProvider(
        response="Fake model received the retrieved context.", cite_sources=True
    )
    report = evaluate_documents(service, baseline, cases)
    report["dataset_sha256"] = hashlib.sha256(dataset_bytes).hexdigest()
    report["commit"] = os.environ.get("GITHUB_SHA", "local")
    report["provider"] = "deterministic_fake"
    report["judge_calibration"] = calibrate_judge(
        json.loads(args.judge_samples.read_text(encoding="utf-8"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {key: value for key, value in report.items() if key != "cases"}
    print(json.dumps(summary, indent=2))
    gate_passed = (
        report["rag"]["task_success"] > report["baseline"]["task_success"]
        and report["rag"]["correct_refusal"] == 1.0
        and report["retrieval_recall_at_5"] >= 0.9
    )
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
