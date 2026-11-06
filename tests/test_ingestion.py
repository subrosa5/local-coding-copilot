from local_coding_copilot.ingestion import load_markdown_documents


def test_markdown_ingestion_assigns_stable_ids_and_content_versions(tmp_path) -> None:
    (tmp_path / "b.md").write_text("second", encoding="utf-8")
    (tmp_path / "a.md").write_text("first", encoding="utf-8")

    documents = load_markdown_documents(tmp_path)

    assert [document.document_id for document in documents] == ["a", "b"]
    assert documents[0].source == "a.md"
    assert len(documents[0].version) == 64

    (tmp_path / "a.md").write_text("updated", encoding="utf-8")
    updated = load_markdown_documents(tmp_path)
    assert updated[0].version != documents[0].version
