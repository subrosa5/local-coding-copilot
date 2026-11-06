# Эксплуатация

**Текущее состояние:** document RAG работает с PostgreSQL/pgvector, fake embeddings и fake LLM. Доступны ingestion CLI, HTTP и MCP. Авторизации нет: используйте только loopback и синтетические документы.

## Установка и запуск

Требуются Python 3.11 или новее и Docker Compose:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
export DATABASE_URL=postgresql://copilot:copilot@127.0.0.1:5432/copilot
python -m local_coding_copilot.rag_cli ingest data/synthetic
python -m local_coding_copilot.smoke
```

Запрос через CLI:

```bash
python -m local_coding_copilot.rag_cli query "What is the maximum order notional?"
```

HTTP на `127.0.0.1:8000`:

```bash
python -m local_coding_copilot.api
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"When is a market data update stale?","limit":3}'
```

MCP stdio server запускается клиентом командой:

```bash
python -m local_coding_copilot.mcp_server
```

Инструмент `query_documents` принимает `question` и опциональный `limit`. HTTP и MCP вызывают один `DocumentRAGService`.

Остановить БД: `docker compose stop db`. Данные сохраняются в Docker volume `copilot-postgres`.

## Проверки разработки

```bash
ruff check .
ruff format --check .
pytest
python -m local_coding_copilot.smoke
```

Без `DATABASE_URL` PostgreSQL/MCP integration-тесты пропускаются. В CI они выполняются с реальным pgvector на Python 3.11 и 3.13. Внешние AI API не используются.

## Будущая локальная конфигурация

Целевой запуск — один домашний ПК, Docker Compose, PostgreSQL/pgvector и OpenAI-compatible model endpoint. Реальные локальные модели и offline-проверка относятся к M7. Модели, runtime-данные и логи хранятся вне Git.

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

Один ПК является single point of failure. Данные о нагрузке, задержках и стабильности публикуются только после реальных измерений. Нельзя использовать предполагаемые показатели как production SLO.
