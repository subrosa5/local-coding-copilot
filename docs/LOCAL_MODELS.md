# Локальные embedding и reranker модели

Из `rag-mcp-agent` перенесены подход с локальными Sentence Transformers
embeddings и cross-encoder reranking. Его Groq/Cohere и MCP orchestration в этот
закрытый контур не переносились. Существующий PostgreSQL hybrid search, RRF и
ACL остаются основой retrieval; reranker применяется только после SQL ACL.

В проект добавлены опциональные provider-адаптеры Sentence Transformers для
локальных embeddings и cross-encoder reranking. Без настроек bootstrap и CI
по-прежнему используют fake providers. Выбор локальной LLM остаётся отдельной
задачей: в исходном `rag-mcp-agent` локального LLM provider нет.

## Установка и запуск

Установите extra `local-models` в окружении, где заранее подготовлены веса.
Скопируйте модели в обычные локальные каталоги без symlinks, затем запустите
offline preflight. Он читает и хеширует все файлы модели, запускает embedding и
reranker smoke checks и сохраняет manifest:

```bash
pip install '.[local-models]'
copilot-model-preflight \
  --embedding-model /opt/models/embedding \
  --reranker-model /opt/models/reranker \
  --device cuda \
  --output /opt/models/model-manifest.json
```

Команда завершается ошибкой при отсутствующих файлах, symlinks, некорректном
выходе модели или недоступном выбранном устройстве. Артефактные SHA-256 и
fingerprint выводятся в JSON; fingerprint меняется при изменении содержимого.
Загрузчики используют `local_files_only=True` и `trust_remote_code=False`, поэтому
runtime не скачивает модели и не исполняет код из model repository.

```bash
export COPILOT_EMBEDDING_MODEL=/opt/models/embedding
export COPILOT_EMBEDDING_FINGERPRINT="$(python -c 'import json; print(json.load(open("/opt/models/model-manifest.json"))["embedding"]["fingerprint"])')"
export COPILOT_RERANKER_MODEL=/opt/models/reranker
export COPILOT_RERANKER_FINGERPRINT="$(python -c 'import json; print(json.load(open("/opt/models/model-manifest.json"))["reranker"]["fingerprint"])')"
export COPILOT_MODEL_DEVICE=cuda
python -m local_coding_copilot.rag_cli ingest data/synthetic --prune-missing
python -m local_coding_copilot.evaluation --output data/runtime/with-reranker.json
unset COPILOT_RERANKER_MODEL COPILOT_RERANKER_FINGERPRINT
python -m local_coding_copilot.evaluation --output data/runtime/without-reranker.json
```

Те же переменные читаются обычными CLI/API/MCP bootstrap. Для CPU укажите
`COPILOT_MODEL_DEVICE=cpu`; если переменную опустить, устройство выберет библиотека.
Reranker необязателен: достаточно не задавать обе переменные `COPILOT_RERANKER_*`.
SQL применяет ACL до reranking; сервис оценивает до четырёх кандидатов на один
результат, максимум 80.
Для локальных embeddings bootstrap использует начальный порог vector score
`0.25`; fake-provider сохраняет тестовый порог `0.99`. Порог можно переопределить
через `COPILOT_MIN_VECTOR_SCORE` и подобрать только по retrieval evaluation.

Bootstrap пока использует fake LLM, если приложение не получает другой
`LLMProvider`. Значит, такой запуск годится для проверки индекса/retrieval, но
fake ответы нельзя считать демонстрацией локальной LLM или показывать как ответы
пользователям.

## Индекс и совместимость

Fingerprint embedding-модели хранится у каждого документа и у каждого code
repository. Document queries fail closed, пока хотя бы один документ проекта не
переиндексирован текущей моделью. `rag_cli ingest` переиндексирует найденные
документы; `--prune-missing` дополнительно удаляет документы, отсутствующие в
источнике, и подходит только для полного канонического каталога проекта. Пустой
каталог отклоняется. Code indexer автоматически полностью переиндексирует
tracked-файлы репозитория при смене модели. Все code repositories проекта нужно
переиндексировать до query. Старые записи после schema migration имеют `NULL`
fingerprint, поэтому их нужно переиндексировать до query.

RAG evaluation записывает `Recall@1/3/5`, `MRR@5`, fingerprints provider-ов и
dataset SHA-256. Сравнение выше использует один и тот же embedding index и golden
set. Метрики считают source retrieval, а не фактическую правильность ответа LLM.

## Границы проверки

Unit-тесты проверяют fingerprint, manifest, fail-closed несовпадение, полную
переиндексацию code при смене модели, offline-загрузку и метрики reranking на
fake-моделях. Preflight проверяет конкретные локальные artifacts на конкретном ПК.
Веса, GPU/VRAM, latency и параллельные запросы не проверялись в этой среде; это
остаётся частью M7 evaluation.
