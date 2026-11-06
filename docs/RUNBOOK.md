# Эксплуатация

**Текущее состояние:** доступен только CLI smoke path с fake LLM. Сетевые сервисы, БД и реальные модели ещё не реализованы.

## Локальный smoke path

Требуется Python 3.11 или новее:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m local_coding_copilot "Hello"
```

Ожидаемый вывод: `Fake provider response.` Команда не обращается к внешним AI API и не демонстрирует RAG.

Проверки разработки:

```bash
ruff check .
ruff format --check .
pytest
```

## Будущая локальная конфигурация

Целевой запуск — один домашний ПК, Docker Compose, локальный PostgreSQL/pgvector и OpenAI-compatible model endpoint. Модели, runtime-данные и логи хранятся вне Git.

Планируемые профили:

- `test` — fake providers и детерминированные CI-проверки;
- `local` — реальные локальные модели;
- `offline` — только ранее загруженные артефакты и запрет внешних AI-соединений.

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
