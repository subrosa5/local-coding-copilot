from local_coding_copilot.models import ChatRequest, Message
from local_coding_copilot.providers import EmbeddingProvider, LLMProvider
from local_coding_copilot.rag.chunking import chunk_document
from local_coding_copilot.rag.grounding import validate_grounding
from local_coding_copilot.rag.models import (
    AnswerMode,
    Citation,
    Document,
    QueryResponse,
    RetrievalTraceItem,
    SearchResult,
)
from local_coding_copilot.rag.repository import DocumentRepository

_REFUSAL = "Недостаточно подтверждённых источников для ответа."


class DocumentRAGService:
    def __init__(
        self,
        repository: DocumentRepository,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
        chunk_size: int = 800,
        min_vector_score: float = 0.25,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._llm = llm
        self._chunk_size = chunk_size
        self._min_vector_score = min_vector_score

    def ingest_document(self, document: Document) -> int:
        chunks = chunk_document(document, max_chars=self._chunk_size)
        embeddings = self._embeddings.embed([chunk.content for chunk in chunks])
        self._repository.replace_document(document, chunks, embeddings)
        return len(chunks)

    def query(
        self, question: str, limit: int = 5, mode: AnswerMode = "grounded"
    ) -> QueryResponse:
        if not question.strip():
            raise ValueError("Question must not be empty")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20")
        if mode not in {"fast", "grounded"}:
            raise ValueError("Mode must be fast or grounded")

        embedding = self._embeddings.embed([question])[0]
        candidates = self._repository.search(question, embedding, limit)
        selected_ids = {
            result.chunk.chunk_id
            for result in candidates
            if result.lexical_score > 0 or result.vector_score >= self._min_vector_score
        }
        results = [
            result for result in candidates if result.chunk.chunk_id in selected_ids
        ]
        retrieval = tuple(
            RetrievalTraceItem(
                chunk_id=result.chunk.chunk_id,
                source=result.chunk.source,
                score=result.score,
                vector_score=result.vector_score,
                lexical_score=result.lexical_score,
                selected=result.chunk.chunk_id in selected_ids,
            )
            for result in candidates
        )
        if not results:
            return self._refusal(mode, retrieval, "no_relevant_evidence")

        response = self._llm.complete(self._build_request(question, results))
        if mode == "fast":
            return QueryResponse(
                answer=response.content,
                citations=tuple(self._citation(result) for result in results),
                retrieval=retrieval,
                mode=mode,
                refused=False,
            )

        grounding = validate_grounding(response.content, results)
        if grounding.reason:
            return self._refusal(mode, retrieval, grounding.reason)
        citations = tuple(
            self._citation(results[index - 1]) for index in grounding.cited_indexes
        )
        return QueryResponse(
            answer=response.content,
            citations=citations,
            retrieval=retrieval,
            mode=mode,
            refused=False,
        )

    @staticmethod
    def _refusal(
        mode: AnswerMode,
        retrieval: tuple[RetrievalTraceItem, ...],
        reason: str,
    ) -> QueryResponse:
        return QueryResponse(
            answer=_REFUSAL,
            citations=(),
            retrieval=retrieval,
            mode=mode,
            refused=True,
            refusal_reason=reason,
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
