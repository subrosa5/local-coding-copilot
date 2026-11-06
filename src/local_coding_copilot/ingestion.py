import hashlib
from pathlib import Path

from local_coding_copilot.rag import Document


def load_markdown_documents(directory: Path) -> tuple[Document, ...]:
    if not directory.is_dir():
        raise ValueError(f"Document directory does not exist: {directory}")

    documents = []
    for path in sorted(directory.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        source = path.relative_to(directory).as_posix()
        documents.append(
            Document(
                document_id=source.removesuffix(".md"),
                source=source,
                version=hashlib.sha256(content.encode()).hexdigest(),
                content=content,
            )
        )
    return tuple(documents)
