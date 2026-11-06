from local_coding_copilot.rag.chunking import chunk_document
from local_coding_copilot.rag.models import Document


def test_chunking_preserves_source_lines() -> None:
    document = Document(
        document_id="rules",
        source="rules.md",
        version="v1",
        content="first line\nsecond line\nthird line",
    )

    chunks = chunk_document(document, max_chars=24)

    assert len(chunks) == 2
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 2)
    assert (chunks[1].start_line, chunks[1].end_line) == (3, 3)
    assert chunks[0].content == "first line\nsecond line"
    assert chunks[1].chunk_id == "rules:1"
