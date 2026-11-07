# Local Coding Copilot

Локальный coding-ассистент с доказательными ответами, RAG по исходному коду, tool calling и изолированным выполнением тестов.

**Статус:** document RAG поддерживает fast/grounded режимы, проверку citations и явный отказ. Реализованы локальные токены, роли, проектные ACL, rate limits и технический audit. Code RAG индексирует tracked Python-файлы через Git и Tree-sitter с commit-aware citations и incremental updates. Coding loop применяет подготовленные unified diff в отдельном worktree и запускает compileall/unittest в Docker без сети; успешный patch ожидает ручного review. Сейчас используются fake embeddings/LLM и детерминированный patch provider, реальные модели относятся к M7.

## Цель

Собрать pre-enterprise POC для 2–3 тестировщиков, который позволит проверить:

- ответы на вопросы по документации с проверяемыми источниками;
- поиск по Git-репозиториям с учётом версии и прав доступа;
- создание минимального patch в отдельном Git worktree;
- запуск сборки, тестов и linters в sandbox без сети;
- измеримое сравнение baseline, RAG и RAG с test loop;
- полностью локальный запуск на домашнем GPU без внешних AI API.

Успешный POC является основанием для решения о **production-пилоте**, а не доказательством готовности к критичному production.

## Принципы

- Сначала один работающий вертикальный сценарий, затем расширение.
- Любое утверждение о проекте сопровождается источником либо явным «не знаю».
- Модельный ответ и сгенерированный код считаются недоверенными.
- Авторизация и разрешения выполняются программно вне LLM.
- Merge выполняет только человек после проверки diff и тестов.
- Качество подтверждается воспроизводимыми измерениями, а не впечатлением от демо.

## Документация

- [Границы и критерии POC](docs/SCOPE.md)
- [Целевая архитектура](docs/ARCHITECTURE.md)
- [План разработки и перенос старого кода](docs/DEVELOPMENT_PLAN.md)
- [Безопасность](docs/SECURITY.md)
- [Оценка качества](docs/EVALUATION.md)
- [Руководство тестировщика](docs/TESTER_GUIDE.md)
- [Эксплуатация](docs/RUNBOOK.md)
- [Отличия POC от production](docs/PRODUCTION_GAP.md)

Правила для AI-ассистентов и разработчиков находятся в [AGENTS.md](AGENTS.md).

## Быстрый запуск

Нужны Python 3.11+ и Docker Compose:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
export DATABASE_URL=postgresql://copilot:copilot@127.0.0.1:5432/copilot
export COPILOT_API_TOKEN=$(python -m local_coding_copilot.security_cli \
  --user-id admin --role admin --project-id default)
python -m local_coding_copilot.rag_cli ingest data/synthetic
python -m local_coding_copilot.smoke
python -m local_coding_copilot.evaluation
python -m local_coding_copilot.rag_cli query "What is the maximum order notional?"
```

Для code RAG нужен чистый checkout синтетического репозитория:

```bash
git clone https://github.com/subrosa5/exchange-demo ../exchange-demo
python -m local_coding_copilot.code_cli index ../exchange-demo \
  --repository exchange-demo
python -m local_coding_copilot.code_cli query "validate_order"
```

HTTP: `python -m local_coding_copilot.api`. MCP stdio: `python -m local_coding_copilot.mcp_server`. Оба используют тот же токен и project ACL. Подробности в [runbook](docs/RUNBOOK.md).

## Проверки

```bash
ruff check .
ruff format --check .
pytest
```

Тесты используют fake/deterministic providers и не требуют внешних AI API. PostgreSQL/MCP integration-тесты требуют `DATABASE_URL` и выполняются в CI с pgvector.

## Связанные репозитории

- `local-coding-copilot` — новая система и её документация.
- [`exchange-demo`](https://github.com/subrosa5/exchange-demo) — отдельный синтетический Git-репозиторий с документацией, тестами и тремя известными дефектами.
- `rag-mcp-agent` — прежний проект; из него переносятся только проверенные изменения отдельными задачами.

## Текущий этап

**M0–M6** завершены: document/code RAG, ACL, security baseline, AST metadata, commit-aware citations, incremental indexing, deterministic coding loop, Git worktree и Docker sandbox проверены в CI. Следующий этап — **M7**: реальные локальные модели, целевой GPU и offline validation. Версия предназначена только для синтетических документов и кода.
