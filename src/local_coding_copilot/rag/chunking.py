from local_coding_copilot.rag.models import Chunk, Document


def chunk_document(document: Document, max_chars: int = 800) -> tuple[Chunk, ...]:
    if max_chars < 1:
        raise ValueError("Chunk size must be positive")
    if not document.content.strip():
        raise ValueError("Document content must not be empty")

    lines = document.content.splitlines()
    chunks = []
    current_lines: list[str] = []
    current_length = 0
    start_line = 1

    def finish_chunk(end_line: int) -> None:
        chunk_index = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=f"{document.document_id}:{chunk_index}",
                document_id=document.document_id,
                source=document.source,
                version=document.version,
                chunk_index=chunk_index,
                start_line=start_line,
                end_line=end_line,
                content="\n".join(current_lines),
            )
        )

    for line_number, line in enumerate(lines, start=1):
        line_length = len(line) + 1
        if current_lines and current_length + line_length > max_chars:
            finish_chunk(line_number - 1)
            current_lines = []
            current_length = 0
        if not current_lines:
            start_line = line_number
        current_lines.append(line)
        current_length += line_length

    if current_lines:
        finish_chunk(len(lines))
    return tuple(chunks)
