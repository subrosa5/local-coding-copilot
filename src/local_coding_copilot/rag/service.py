from local_coding_copilot.models import ChatRequest, Message
from local_coding_copilot.providers import EmbeddingProvider, LLMProvider
from local_coding_copilot.rag.chunking import chunk_document
from local_coding_copilot.rag.models import (
    Citation,
    Document,
    QueryResponse,
    RetrievalTraceItem,
    SearchResult,
)
from local_coding_copilot.rag.repository import DocumentRepository


class DocumentRAGService:
    def __init__(
        self,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
        chunk_size: int = 800,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._llm = llm
        self._chunk_size = chunk_size

    def ingest_document(self, document: Document) -> int:
        chunks = chunk_document(document, max_chars=self._chunk_size)
        embeddings = self._embeddings.embed([chunk.content for chunk in chunks])
        self._repository.replace_document(document, chunks, embeddings)
        return len(chunks)

    def query(self, question: str, limit: int = 5) -> QueryResponse:
        if not question.strip():
            raise ValueError("Question must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20")

        embedding = self._embeddings.embed([question])[0]
        results = self._repository.search(question, embedding, limit)
        response = self._llm.complete(self._build_request(question, results))
        return QueryResponse(
            answer=response.content,
            citations=tuple(self._citation(result) for result in results),
            retrieval=tuple(
                RetrievalTraceItem(
                    chunk_id=result.chunk.chunk_id,
                    source=result.chunk.source,
                    score=result.score,
                    vector_score=result.vector_score,
                    lexical_score=result.lexical_score,
                )
                for result in results
            ),
        )

    def _build_request(self, question: str, results: list[SearchResult]) -> ChatRequest:
        context = "\n\n".join(
            f"[{index}] {result.chunk.source}:{result.chunk.start_line}-"
            f"{result.chunk.end_line}@{result.chunk.version}\n{result.chunk.content}"
            for index, result in enumerate(results, start=1)
        )
        return ChatRequest(
            messages=(
                Message(
                    role="system",
                    content=(
                        "Answer only from the supplied context. If it is insufficient, "
                        "say so. Cite sources by their bracketed numbers."
                    ),
                ),
                Message(
                    role="user",
                    content=f"Question: {question}\n\nContext:\n{context}",
                ),
            )
        )

    @staticmethod
    def _citation(result: SearchResult) -> Citation:
        chunk = result.chunk
        return Citation(
            document_id=chunk.document_id,
            source=chunk.source,
            version=chunk.version,
            chunk_id=chunk.chunk_id,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            text=chunk.content,
        )
