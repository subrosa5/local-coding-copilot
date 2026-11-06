# Целевая архитектура

Документ описывает целевое устройство. Наличие компонента здесь не означает, что он уже реализован.

## Схема

```text
HTTP client / MCP client / IDE
              │
       API + Auth + Quotas
              │
        Coding Orchestrator
        ┌─────┼─────────────┐
        │     │             │
   Retrieval  LLM       Git Workspace
        │     │             │
 hybrid RAG   │        patch + diff
        │     │             │
 PostgreSQL   │        Sandbox Runner
 pgvector     │        build/test/lint
        │     │             │
 Git + docs + ACL      Audit + Metrics
```

## Компоненты

### API и MCP

FastAPI HTTP и MCP stdio вызывают один `DocumentRAGService`. Они не содержат отдельных реализаций retrieval или orchestration. Авторизация будет добавлена в M4; текущие транспорты предназначены только для локальных синтетических данных.

### Provider interfaces

В `src/local_coding_copilot/providers/contracts.py` определены независимые контракты:

- `LLMProvider` — chat/tool calling; адаптеры внешнего или OpenAI-compatible local endpoint ещё предстоит реализовать;
- `EmbeddingProvider` — embeddings;
- `RerankerProvider` — reranking;
- fake implementations — детерминированные CI-тесты без внешних API.

POC не должен зависеть от конкретного облачного провайдера.

### Retrieval

Document RAG использует PostgreSQL full-text и pgvector candidates, объединённые через Reciprocal Rank Fusion. Повторная индексация атомарно заменяет документ и его chunks. Ответ содержит `source:start_line-end_line@version` и retrieval trace со vector/lexical scores.

Для code RAG в M5 дополнительно планируются `ripgrep`, Tree-sitter, AST metadata и commit-aware citations. Reranker provider пока не подключён к document pipeline.

Текущая document-запись содержит:

```text
document_id/source/version/chunk_id
start_line/end_line/content/embedding
```

Project ACL, repository, symbol и commit metadata будут добавлены вместе с соответствующими этапами.

### Orchestrator

Начальная реализация — явная конечная state machine без дополнительного agent framework.

Режимы:

- `fast` — основной agent без необязательных вызовов;
- `grounded` — расширенные проверки и critic;
- `eval` — воспроизводимые параметры и сохранение результатов.

Coding workflow ограничен числом итераций и не может самостоятельно выполнить merge.

### Git workspace и sandbox

Изменения выполняются только в отдельном Git worktree. Код запускается в одноразовом контейнере с отключённой сетью, non-root пользователем, read-only root и лимитами CPU/RAM/времени.

### Хранение

POC использует минимальное число хранилищ:

- PostgreSQL/pgvector — chunks, ACL, eval metadata и состояние;
- Git — исходный код и версии;
- локальное файловое хранилище — модели и временные runtime-артефакты вне Git.

### Наблюдаемость

Сохраняются технические метаданные: пользователь, проект, модель, commit, tool calls, latency, tokens, hash diff и результаты тестов. Полные prompt/response по умолчанию отключены.

## Потоки

### Вопрос по проекту

`authenticate → authorize → retrieve → rerank → generate → validate citations → respond`

При недостатке доказательств система возвращает явный отказ.

### Coding-задача

`task → retrieve → plan → worktree → patch → build/test/lint → bounded repair → review → diff`

Тесты выполняются в sandbox. Изменение существующих тестов отдельно отмечается при review.

## Перенос прежнего проекта

Из `rag-mcp-agent` можно поэтапно переносить проверенные решения hybrid retrieval, provider adapters, MCP transport и eval harness. Новая архитектура не требует Qdrant или LangGraph на старте.
