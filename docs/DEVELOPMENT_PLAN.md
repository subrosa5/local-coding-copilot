# План разработки

Работа выполняется последовательно небольшими PR. GPU-этап отложен: сначала реализуются и проверяются в CI документация, интерфейсы, retrieval, безопасность и orchestration.

## Статусы

- `todo` — задача не начата;
- `in_progress` — активная задача, одновременно допускается только одна основная;
- `done` — acceptance criteria выполнены и проверки зелёные;
- `blocked` — указан конкретный блокер.

## M0 — Проектный baseline

**Статус:** done.

- Создать независимый репозиторий.
- Зафиксировать scope, архитектуру, безопасность и evaluation plan.
- Установить правила работы AI-ассистентов.

**Gate:** документация проверена, относительные ссылки работают, секреты отсутствуют.

## M1 — Минимальный каркас и CI

**Статус:** done.

- Создать минимальный Python application skeleton.
- Определить provider contracts и fake implementations.
- Настроить pytest, lint и GitHub Actions.
- Добавить Docker Compose skeleton только для реально существующих сервисов.

**Gate:** чистый checkout проходит CI; тесты не требуют внешних API.

## M2 — Локальный document RAG baseline

**Статус:** done.

- PostgreSQL/pgvector и ingestion синтетических документов.
- Hybrid retrieval и provider-based embeddings.
- HTTP/MCP на одном application service.
- Базовый trace retrieval.

**Gate:** заданный document smoke set воспроизводимо выполняется локально/в CI с fake model.

## M3 — Grounding и оценка качества

**Статус:** done.

- Проверяемые citations и явный отказ.
- Fast/grounded режимы.
- Golden set 30–50 вопросов.
- Retrieval metrics и валидация LLM-judge на ручной разметке.

**Gate:** результаты baseline и RAG сравнимы на одной версии набора.

## M4 — Auth, ACL и security baseline

**Статус:** done.

- Локальные пользователи, tokens, роли и проектные ACL.
- Rate limits, audit и секретные/личные данные вне логов.
- Prompt-injection и cross-project security tests.

**Gate:** запрещённые retrieval/tool calls блокируются программно на HTTP и MCP.

## M5 — Code RAG и `exchange-demo`

**Статус:** done.

- Создать синтетический `exchange-demo` с документацией, тестами и известными дефектами.
- Tree-sitter, exact search, AST metadata и commit-aware citations.
- Инкрементальная индексация изменений и удалений.

**Gate:** ассистент находит целевые символы и правила, а индекс соответствует commit.

## M6 — Coding loop и sandbox

**Статус:** done.

- Git worktree, unified diff, compileall и unittest.
- Sandbox без сети и секретов, resource limits и timeout.
- Не более двух repair iterations.
- Review diff и обязательное human approval.

**Gate:** несколько подготовленных задач дают реальный проверенный patch; запрещённые действия блокируются.

## M7 — Реальная локальная LLM и offline validation

**Статус:** in_progress (provider, model patch workflow, benchmark harness и fake-HTTP integration покрыты кодом/CI; hardware/model validation ещё не начата).

- Код завершён: сменный provider для OpenAI-compatible loopback endpoint; fake HTTP tests не обращаются к внешним AI API.
- Код завершён: настроенная LLM подключена к document/code RAG; embeddings пока fake, reranker не включён.
- Код завершён: model-based patch generation подключена к `PatchProvider`/coding orchestration; tool calls валидируются по allowlist/schema, unified diff — до `git apply`.
- Код/CI завершены: сквозной scripted fake HTTP → model patch → worktree → sandbox → repair/audit. Это integration simulation, не model generation benchmark и не hardware validation.
- Осталось: запустить quantized coding model на RTX 4070 Ti — сначала 7B, затем сравнить с 14B при наличии VRAM.
- Осталось: проверить initial patch и максимум две repair iterations на реальных запусках модели.
- Осталось: подключить локальные embeddings и оценить retrieval на зафиксированном наборе; reranker добавлять только при измеримом улучшении.
- Осталось: расширить coding benchmark независимыми acceptance tests; текущие три задачи являются smoke-level baseline.
- Осталось: измерить VRAM/RAM, latency, tokens/sec, полное время coding-задачи, verified success и human acceptance.
- Осталось: предварительно загрузить модели и Docker images; проверить offline после отключения интернета.
- Осталось: записать фактические результаты и ограничения. CI продолжает использовать fake/deterministic providers без GPU и внешних AI API.

**Gate:** настоящий локальный provider и embeddings проходят coding/RAG сценарии; расширенный benchmark и offline-проверка выполнены на целевом ПК; фактические показатели и ограничения задокументированы. Успешный GitHub CI или scripted fake endpoint сами по себе не подтверждают качество генерации, работу GPU, offline или производительность.

## M8 — Приёмка тестировщиками

**Статус:** todo.

- Заморозить тестовый tag.
- Провести одинаковые сценарии без помощи автора.
- Исправить только критичные находки и повторить benchmark.
- Подготовить demo и production gap review.

**Gate:** принято go/conditional-go/no-go для production-пилота с перечнем условий.

## M9 — Optional training experiment

**Статус:** todo, не блокирует POC.

- Классифицировать ошибки baseline.
- При retrieval-ошибках рассмотреть embedding/reranker tuning.
- При устойчивых поведенческих ошибках рассмотреть небольшой LoRA.
- Сравнить Base, Base+RAG, LoRA и LoRA+RAG без leakage eval-задач.

**Gate:** обучение включается в контур только при воспроизводимом улучшении.

## Перенос из `rag-mcp-agent`

1. Дождаться завершения и ревью соответствующей ветки Astra.
2. Выбрать конкретное поведение, необходимое текущей milestone.
3. Перенести только связанные файлы/фрагменты и адаптировать к новым контрактам.
4. Перенести или переписать тесты так, чтобы они не требовали внешних API.
5. Проверить отсутствие секретов, cloud-only assumptions и устаревшей документации.
6. Оформить отдельный PR с указанием источника и фактических проверок.

Запрещён wholesale copy всего старого репозитория. Приоритет: provider adapters, hybrid retrieval, reranking, MCP reuse, eval structure и проверенные grounding/security tests.

## Формат новой задачи

```text
ID и название:
Milestone:
Цель:
Входит в задачу:
Не входит в задачу:
Затрагиваемые компоненты:
Acceptance criteria:
Проверки:
Обновления документации:
```
