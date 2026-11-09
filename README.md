# Local Coding Copilot

Локальный coding-ассистент с доказательными ответами, RAG по исходному коду, tool calling и изолированным выполнением тестов.

**Статус:** M0–M6 и программная часть M7 находятся в `main`. Document RAG поддерживает fast/grounded режимы, проверку citations и отказ при недостатке evidence. Реализованы локальные токены, роли, project ACL, rate limits и технический audit. Code RAG индексирует tracked Python-файлы из Git commit через Tree-sitter. Coding loop использует OpenAI-compatible loopback provider, создаёт model-based diff и проверяет его в Docker до human review. Benchmark сравнивает Base, RAG и RAG + test loop на трёх синтетических задачах. Embeddings остаются fake, reranker не подключён; реальная модель, GPU, offline и качество на ней не проверены.

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

Чтобы запустить программный M7-путь, укажите локальный OpenAI-compatible endpoint в `COPILOT_LLM_BASE_URL` и имя модели в `COPILOT_LLM_MODEL`. Provider принимает только loopback HTTP URL; redirects и системные proxy отключены. Сгенерированный diff ограничен существующими файлами, проверяется до `git apply` и исполняется только через Docker sandbox. Сам endpoint и модель нужно отдельно установить на целевой машине; hardware/offline gate ещё не пройдены. См. [runbook](docs/RUNBOOK.md).

HTTP: `python -m local_coding_copilot.api`. MCP stdio: `python -m local_coding_copilot.mcp_server`. Оба используют тот же токен и project ACL. Подробности в [runbook](docs/RUNBOOK.md).

## Проверки

```bash
ruff check .
ruff format --check .
pytest
```

Тесты используют fake/deterministic providers и не требуют внешних AI API. Test-only scripted HTTP endpoint дополнительно проверяет сквозной путь provider → model patch → validation → worktree → sandbox → repair/audit; его mock diff не считается генерацией модели и не участвует в benchmark. Такая симуляция подтверждает интеграцию и защитный контур, но не качество генерации, производительность, GPU, offline или работу настоящей модели. Embeddings пока fake. PostgreSQL/MCP integration-тесты требуют `DATABASE_URL` и выполняются в CI с pgvector.

## Связанные репозитории

- `local-coding-copilot` — новая система и её документация.
- [`exchange-demo`](https://github.com/subrosa5/exchange-demo) — отдельный синтетический Git-репозиторий с документацией, тестами и тремя известными дефектами.
- `rag-mcp-agent` — прежний проект; из него переносятся только проверенные изменения отдельными задачами.

## Текущий этап

**M0–M6 и кодовая часть M7** влиты и проверены в CI. M7 остаётся незавершённым до запуска настоящей модели на RTX 4070 Ti, подключения локальных embeddings, измерений качества/latency/VRAM/RAM и offline-проверки. Текущий benchmark содержит три синтетические задачи и является только начальной проверкой. Используйте только синтетические документы и код.
