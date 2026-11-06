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

**Статус:** todo.

- Локальные пользователи, tokens, роли и проектные ACL.
- Rate limits, audit и секретные/личные данные вне логов.
- Prompt-injection и cross-project security tests.

**Gate:** запрещённые retrieval/tool calls блокируются программно на HTTP и MCP.

## M5 — Code RAG и `exchange-demo`

**Статус:** todo.

- Создать синтетический `exchange-demo` с документацией, тестами и известными дефектами.
- Tree-sitter, exact search, AST metadata и commit-aware citations.
- Инкрементальная индексация изменений и удалений.

**Gate:** ассистент находит целевые символы и правила, а индекс соответствует commit.

## M6 — Coding loop и sandbox

**Статус:** todo.

- Git worktree, unified diff, build/test/lint.
- Sandbox без сети и секретов, resource limits и timeout.
- Не более двух repair iterations.
- Review diff и обязательное human approval.

**Gate:** несколько подготовленных задач дают реальный проверенный patch; запрещённые действия блокируются.

## M7 — Целевой ПК и offline validation

**Статус:** todo.

- Запустить выбранную quantized coding model на 4070 Ti.
- Проверить local providers, VRAM/RAM, latency и 2–3 пользователей.
- Проверить offline после предварительной загрузки артефактов.
- Выполнить полный benchmark с реальной моделью.

**Gate:** задокументированы фактические показатели; непроверенные заявления отсутствуют.

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
