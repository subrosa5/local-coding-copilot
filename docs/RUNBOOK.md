# Эксплуатация

**Текущее состояние:** M0–M6 и программная часть M7 влиты в `main`. Без LLM-настроек приложение использует fake LLM и fake embeddings. Coding CLI поддерживает OpenAI-compatible loopback inference endpoint и model-generated patch. Реальная модель, настоящие embeddings, GPU и offline пока не проверены. Все операции с документами требуют локальный токен и project membership; ingestion разрешён только admin. Используйте только синтетические документы.

## Установка и запуск

Требуются Python 3.11 или новее и Docker Compose:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
export DATABASE_URL=postgresql://copilot:copilot@127.0.0.1:5432/copilot
```

Создайте первого admin для проекта `default`. Команда один раз печатает случайный plaintext token; в PostgreSQL сохраняется только его SHA-256:

```bash
export COPILOT_API_TOKEN=$(python -m local_coding_copilot.security_cli \
  --user-id admin --role admin --project-id default)
python -m local_coding_copilot.rag_cli ingest data/synthetic
python -m local_coding_copilot.smoke
```

Для тестировщика с доступом только на чтение:

```bash
python -m local_coding_copilot.security_cli \
  --user-id tester-1 --role viewer --project-id default
```

Передайте тестировщику выданный token по отдельному защищённому каналу. Он задаётся как `COPILOT_API_TOKEN` для CLI/MCP или как Bearer token для HTTP. Повторный запуск `security_cli` для того же пользователя создаёт новый token и добавляет указанные project memberships; существующие memberships не удаляются.

## Запросы

CLI в grounded-режиме (по умолчанию) или fast:

```bash
python -m local_coding_copilot.rag_cli query "What is the maximum order notional?"
python -m local_coding_copilot.rag_cli query "Unknown question" --mode fast
```

Для другого доступного проекта добавьте `--project-id PROJECT`. Этот аргумент выбирает проект, но не предоставляет прав: membership проверяется по токену.

Grounded требует существующие citations и проверяет числа по процитированному тексту. При отсутствии релевантных источников оба режима возвращают `refused=true` с машинным `refusal_reason`.

HTTP на `127.0.0.1:8000`:

```bash
python -m local_coding_copilot.api
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/v1/query \
  -H "Authorization: Bearer $COPILOT_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"When is a market data update stale?","limit":3,"project_id":"default"}'
```

Отсутствующий или неверный token возвращает 401, запрет проекта или роли — 403, превышение лимита — 429. `/health` остаётся публичным и не раскрывает данные.

MCP stdio server запускается клиентом командой с `DATABASE_URL` и `COPILOT_API_TOKEN` в окружении:

```bash
python -m local_coding_copilot.mcp_server
```

Инструмент `query_documents` принимает `question`, опциональные `limit`, `mode` и `project_id`. Token не передаётся аргументом tool call. HTTP и MCP вызывают один application service и одни проверки ACL.

Остановить БД: `docker compose stop db`. Данные сохраняются в Docker volume `copilot-postgres`.

## Code RAG

Клонируйте отдельный синтетический репозиторий и убедитесь, что его worktree чистый. Индексатор читает только tracked `.py` файлы и отклоняет незакоммиченные изменения, чтобы commit citation соответствовал содержимому:

```bash
git clone https://github.com/subrosa5/exchange-demo ../exchange-demo
git -C ../exchange-demo status --short
python -m local_coding_copilot.code_cli index ../exchange-demo \
  --repository exchange-demo --project-id default
python -m local_coding_copilot.code_cli query "validate_order" \
  --project-id default
```

Повторный `index` после нового commit сравнивает content hashes, переиндексирует только изменённые пути и удаляет chunks удалённых файлов. Ответ содержит `repository`, `source` (path), `symbol`, `symbol_kind`, line range, `commit_sha` и те же grounding/refusal поля, что document RAG. Изменение неизменённого файла не требует нового embedding, но его commit metadata обновляется на текущий проиндексированный SHA.

HTTP endpoint: `POST /v1/code/query` с тем же Bearer auth и JSON, что `/v1/query`. MCP tool: `query_code`. Оба используют общий code service и project ACL. Indexing требует admin; viewer может только искать в своих проектах.

В M5 поддерживается Python. Другие языки, очередь фоновой индексации, большие monorepo и reranker не входят в текущий gate.

## Coding loop и ручной review

Предварительно загрузите образ и используйте admin token проекта. Исходный checkout должен быть чистым. Для генерации patch задайте локальный inference endpoint; provider принимает только loopback HTTP URL, не использует системный proxy и не следует redirects:

```bash
export COPILOT_LLM_BASE_URL=http://127.0.0.1:8080/v1
export COPILOT_LLM_MODEL=your-local-model-id
# Только если локальный server требует Bearer auth:
# export COPILOT_LLM_API_KEY=local-only-token
export COPILOT_LLM_TIMEOUT_SECONDS=120
export COPILOT_LLM_MAX_TOKENS=8192
```

Endpoint должен предоставлять `POST /v1/chat/completions`. Запустите выбранный локальный inference server отдельно и привяжите его к loopback интерфейсу. Конкретная модель и команда запуска зависят от целевого ПК; они ещё не валидированы на M7 hardware gate.

Индексируйте тот же чистый commit `exchange-demo`, на котором будет строиться worktree:

```bash
python -m local_coding_copilot.code_cli index ../exchange-demo \
  --repository exchange-demo --project-id default
```

По умолчанию coding CLI использует реальный endpoint, grounded code citations и model-generated patch:

```bash
docker pull python:3.11-slim
python -m local_coding_copilot.coding_cli \
  --repository ../exchange-demo --task-id notional-boundary \
  --project-id default
```

`--context-mode base` отключает retrieval и передаёт модели ограниченный snapshot tracked Python-файлов из указанного Git commit (до 200 файлов, не более 16 KiB на файл и 24 KiB суммарно). Это baseline без retrieval, но с исходным кодом. Для детерминированной демонстрации M6 выберите `--patch-provider static`; она читает prepared patch из M6 dataset и не является генерацией LLM.

Доступные task ID: `notional-boundary`, `price-time-priority`, `stale-threshold`. В LLM-режиме CLI получает кодовые citations текущего commit и просит модель вернуть только raw unified diff. Проверка отклоняет prose/Markdown, binary/mode changes, добавление/удаление/rename, traversal, `.git` и symlink paths; затем `git apply --check` выполняется в отдельном worktree. CLI запускает `compileall` и `unittest` в Docker без сети. Допускается первоначальная попытка и максимум два repair. Невалидный diff не применяется и расходует одну попытку repair. Успешный diff остаётся для human review; автоматического merge нет.

При успехе статус `awaiting_review`, а JSON содержит worktree, base commit, diff, diff SHA-256, changed files, `tests_changed`, stdout/stderr tails и результаты build/test. Подготовленные исправления удаляют соответствующий `@unittest.expectedFailure`, поэтому `tests_changed=true` ожидаемо, но обязательно проверяется человеком. Статус не означает approval или merge.

Проверьте diff и тесты вручную. Merge выполняется только человеком вне этого CLI. После review удалите временный worktree, подставив путь из результата:

```bash
git -C ../exchange-demo worktree remove --force /absolute/path/from/result
```

Не удаляйте worktree до завершения review. При ошибке исследуйте технические tails в JSON; полные логи и diff не записываются в audit.

### M7 coding benchmark

После индексации `exchange-demo` и запуска локального endpoint сравните три конфигурации:

```bash
copilot-coding-evaluation \
  --repository ../exchange-demo \
  --tasks evals/coding_benchmark.json \
  --project-id default \
  --output data/runtime/m7-coding-evaluation.json
```

Runner выполняет Base, RAG и RAG + test loop на одном base commit. Benchmark dataset разрешает только `task_id` и `instructions`; runner не открывает `evals/coding_tasks.json` или prepared patches. Сейчас в dataset три синтетические задачи, поэтому это smoke-level baseline, не оценка обобщающего качества. Каждая задача получает отдельный detached worktree; после сохранения diff hash и метрик benchmark удаляет созданный им worktree. Отчёт не содержит prompts, responses или diff body. `human_acceptance` остаётся `null` до ручной разметки. Метрики verified-rate отражают прохождение текущих compileall/unittest, не независимых hidden acceptance tests.

## Rate limits и audit

В POC действует in-memory sliding window: 60 запросов на пользователя за 60 секунд. Лимит применяется после аутентификации и до embeddings/retrieval. Он отдельный для каждого процесса, сбрасывается при перезапуске и не является distributed production-лимитом.

`audit_events` фиксирует пользователя, проект, действие, transport, outcome, причину отказа, timestamp и небольшие технические metadata. Успешные и отклонённые запросы, denied ACL/role/rate-limit и ingestion записываются для известного principal. Полные вопросы, prompt, ответы, содержимое документов и tokens туда не записываются.

## Проверки разработки

```bash
ruff check .
ruff format --check .
pytest
python -m local_coding_copilot.smoke
python -m local_coding_copilot.evaluation
```

Evaluation сохраняет `data/runtime/m3-evaluation.json`, сравнивает baseline и grounded RAG на одном SHA-256 dataset и проверяет recall@5, correct refusal и false refusal rate. CI сохраняет отчёт как artifact для каждой версии Python.

Без `DATABASE_URL` PostgreSQL/MCP integration-тесты пропускаются. Без Docker daemon пропускаются sandbox integration-тесты. В CI эти проверки выполняются с реальными pgvector/Docker на Python 3.11 и 3.13, включая cross-project ACL, HTTP, MCP, rate-limit, audit и сквозной fake inference → model patch → sandbox сценарий. Scripted mock diff находится только в test fixtures, не загружается benchmark и не считается генерацией модели. Внешние AI API не используются; успешная симуляция не заменяет hardware/model validation на целевом ПК.

## Будущая локальная конфигурация

Целевой запуск — один домашний ПК, Docker Compose, PostgreSQL/pgvector и OpenAI-compatible model endpoint. Реальные локальные модели, embeddings и offline-проверка остаются незакрытой частью M7. Модели, runtime-данные и логи хранятся вне Git.

## Что должно быть задокументировано к приёмке

- Поддерживаемые ОС и версии Docker/NVIDIA tooling.
- Установка и получение моделей.
- Инициализация БД и индексация.
- Создание тестовых пользователей.
- Start/stop/restart и health checks.
- Просмотр метрик и безопасных логов.
- Обновление на новый tag и rollback.
- Backup/restore PostgreSQL и индексов.
- Очистка временных worktrees и sandbox containers.
- Offline checklist и диагностика типовых ошибок.

## Эксплуатационные ограничения POC

Один ПК является single point of failure. Нет SSO, MFA, token expiration, удобного revocation workflow и distributed rate limiting. Данные о нагрузке, задержках и стабильности публикуются только после реальных измерений. Нельзя использовать предполагаемые показатели как production SLO.
