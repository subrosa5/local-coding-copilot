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

FastAPI HTTP и MCP stdio вызывают один `Application` с общими `DocumentRAGService` и auth service. Они не содержат отдельных реализаций retrieval или orchestration. HTTP аутентифицирует Bearer token, MCP получает токен из окружения процесса. Права определяются по записи токена и project membership в PostgreSQL, а не по аргументам запроса. Транспорты предназначены только для локальных синтетических данных.

### Provider interfaces

В `src/local_coding_copilot/providers/contracts.py` определены независимые контракты:

- `LLMProvider` — chat/tool calling; адаптеры внешнего или OpenAI-compatible local endpoint ещё предстоит реализовать;
- `EmbeddingProvider` — embeddings;
- `RerankerProvider` — reranking;
- fake implementations — детерминированные CI-тесты без внешних API.

POC не должен зависеть от конкретного облачного провайдера.

### Retrieval

Document RAG использует PostgreSQL full-text и pgvector candidates, объединённые через Reciprocal Rank Fusion. SQL CTE `visible_chunks` ограничивает chunks membership пользователя и выбранным проектом до обоих candidate generators. Повторная индексация атомарно заменяет документ и его chunks. Внутренний document ID имеет namespace проекта, поэтому одинаковые пути разных проектов не перезаписывают друг друга. Ответ содержит `source:start_line-end_line@version`, project ID и retrieval trace со vector/lexical scores.

Code RAG индексирует только tracked Python-файлы чистого Git checkout. Tree-sitter извлекает классы, функции и методы с qualified symbol names и line ranges. PostgreSQL выполняет exact path/symbol/content search, full-text и pgvector retrieval с RRF; ACL действует до candidate generation. Citations содержат repository, path, symbol, lines и commit SHA. Incremental indexer сравнивает SHA-256 содержимого, заменяет только изменённые файлы, удаляет исчезнувшие и обновляет commit metadata без повторной векторизации неизменённых файлов. Reranker provider пока не подключён.

Текущая document-запись содержит:

```text
project_id/document_id/source/version/chunk_id
start_line/end_line/content/embedding
```

Code chunks дополнительно содержат `repository/path/content_sha256/symbol/symbol_kind/commit_sha`; таблица `code_repositories` фиксирует последний полностью проиндексированный commit.

### Orchestrator

Document query реализован без дополнительного agent framework.

Режимы:

- `fast` — retrieval и один LLM-вызов без обязательной citation validation;
- `grounded` — relevance filtering, обязательные существующие citations и проверка числовых утверждений по процитированному тексту;
- `eval` — отдельный runner с фиксированным dataset, fake provider и сохранением результатов.

Оба режима отказывают при отсутствии релевантных источников. Grounding-проверки не доказывают смысловую истинность каждого утверждения и не являются security boundary. LLM-judge используется только в отдельной calibration harness, не в production answer path.

`CodingOrchestrator` доступен через CLI только admin с membership в проекте. Он делает первую попытку и не более двух repair iterations, получая unified diff через `PatchProvider`. Текущий `StaticPatchProvider` читает заранее подготовленные `.patch` файлы: это deterministic harness для проверки orchestration, а не генерация кода LLM. После compileall и unittest результат `awaiting_review` содержит diff, SHA-256, changed files, признак изменения тестов и технические результаты проверок. Merge API отсутствует.

### Git workspace и sandbox

`GitWorktreeManager` требует чистый исходный checkout, создаёт detached worktree от зафиксированного commit и применяет patch через `git apply`. Исходный checkout не редактируется. Рабочие worktrees сохраняются для review и удаляются человеком отдельной командой.

`DockerSandbox` монтирует только disposable worktree как `/workspace`. Контейнер получает `network=none`, read-only root, non-root UID/GID, `cap-drop=ALL`, `no-new-privileges`, 512 МБ RAM, 1 CPU, лимит 128 процессов и timeout. Host environment и Docker socket внутрь не передаются. При timeout runner принудительно удаляет только созданный им контейнер. Это POC-изоляция, а не замена отдельным CI-нодам или более сильному sandbox для недоверенного production-кода.

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
