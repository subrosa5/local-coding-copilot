import json
from pathlib import Path


def test_golden_dataset_has_30_unique_manually_mapped_cases() -> None:
    cases = json.loads(Path("evals/document_golden.json").read_text(encoding="utf-8"))

    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30
    assert sum(not case["answerable"] for case in cases) == 4
    for case in cases:
        for source in case["expected_sources"]:
            assert Path("data/synthetic", source).is_file()
        assert bool(case["expected_sources"]) == case["answerable"]
