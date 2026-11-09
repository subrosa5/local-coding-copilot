# Безопасность

## Активы

- Исходный код и архитектурная документация.
- Права пользователей и project membership.
- Модели, индексы, embeddings и retrieval traces.
- Audit-записи и результаты тестов.

В POC запрещены реальные секреты, production-дампы, персональные данные и ключи биржи.

**Текущее состояние M4:** HTTP использует Bearer token, MCP и CLI получают `COPILOT_API_TOKEN` из окружения. В БД сохраняется только SHA-256 от случайного токена. Project membership проверяется в application service и в SQL до vector/lexical retrieval. Ingestion доступен только admin. Эти контроли не делают POC production-ready: нет SSO, token expiration/revocation UI и distributed rate limiting. Сервис остаётся на loopback/stdio и только с синтетическими документами. Пароли в `compose.yaml` являются локальными тестовыми credentials, не production-секретами.

## Основные угрозы

- Прямой и косвенный prompt injection через вопрос, issue, документ или комментарий в коде.
- Cross-project/cross-user утечка через retrieval, MCP или кэш.
- Несанкционированный tool call.
- Выполнение вредоносного сгенерированного кода.
- Утечка кода через логи, телеметрию или внешний provider.
- Подмена модели, зависимости или container image.
- Изменение тестов для ложного прохождения задачи.

## Обязательные контроли

### Авторизация

- Пользователь и проектные права определяются доверенным backend.
- ACL применяются до retrieval и при повторном чтении источника.
- HTTP и MCP используют один authorization service.
- Идентификатор проекта из запроса не является доказательством права доступа.
- Viewer может выполнять query только в своих проектах; ingestion требует admin и membership.
- In-memory rate limiter ограничивает 60 запросов на пользователя за 60 секунд в каждом процессе. Для нескольких реплик нужен отдельный distributed контроль.
- Audit хранит технические outcome/reason и не содержит полные prompt/response или plaintext token.

### Tools и модель

- Модельный ответ и retrieved content считаются недоверенными данными.
- Tool arguments валидируются по схеме и политике вне LLM.
- Guardrail/critic являются дополнительными проверками, не security boundary.
- Внешние providers отключены в local/offline режиме.
- M7 OpenAI-compatible provider принимает только HTTP loopback endpoints, отключает proxy и redirect forwarding, ограничивает размер ответа и не пишет тело ошибок/секреты в сообщения.
- Имена и аргументы возвращённых tool calls проверяются по tool allowlist и поддерживаемому подмножеству JSON Schema; неизвестные schema keywords отклоняются. M7 coding patch provider tool calls не принимает.
- Unified diff проверяется до `git apply`: ограничены размер и число файлов; traversal, `.git`, binary/mode changes, add/delete/rename и symlink targets отклоняются. `git apply --check` остаётся обязательным.
- Merge, production access и опасные network tools не предоставляются агенту.

### Sandbox

- M6 запускает каждый build/test в отдельном одноразовом Docker container с `network=none`, non-root, read-only root и writable `/workspace`.
- Действуют лимиты 512 МБ RAM, 1 CPU, 128 PIDs и timeout; после timeout удаляется только контейнер со сгенерированным именем.
- Монтируется только disposable Git worktree. Host Docker socket, host environment и production credentials в контейнер не передаются.
- Coding task разрешён только admin с project membership; авторизация выполняется до создания worktree.
- `tests_changed` и diff SHA включаются в review/audit. Изменённые тесты требуют человеческой проверки: успешный unittest сам по себе не доказывает корректность patch.
- Интеграционные тесты проверяют network denial, отсутствие host paths/socket, read-only root, non-root и timeout. Лимиты памяти/CPU настроены, но стресс-тестирование изоляции и ресурсов ещё не выполнено.
- Вывод контейнера читается потоково и сохраняется только ограниченный хвост, чтобы вывод недоверенного процесса не накапливался целиком в памяти хоста.
- Code indexer читает regular blobs из зафиксированного Git tree и отклоняет tracked Python symlinks; пути не открываются через рабочую файловую систему checkout.
- Для production рассматриваются gVisor/Kata/VM и отдельные CI-ноды; Docker POC не является гарантией против всех container escape.

### Логи и аудит

- По умолчанию логируются только технические метаданные и решения безопасности.
- Полные prompt/response отключены.
- Доступ к audit ограничен; сроки хранения должны быть заданы до реальных данных.
- Изменение тестов и security-чувствительных файлов отдельно отмечается.

### Поставка

- Зависимости и модели фиксируются по версии; хэши артефактов проверяются при offline-переносе.
- CI не должен выводить секреты.
- Git-репозиторий не используется для хранения моделей и секретов.

## Минимальные security-тесты POC

1. Пользователь A запрашивает проект B напрямую и через косвенный вопрос.
2. Запрещённый project ID подставляется в tool arguments.
3. Документ содержит инструкцию раскрыть prompt или выполнить tool.
4. Сгенерированный код пытается открыть сеть и прочитать файл вне workspace.
5. Задача превышает время, память и число repair iterations.
6. Агент пытается изменить тесты или выполнить merge.
7. Полные секретные значения не появляются в логах.
8. M7 отвергает удалённый endpoint, redirects, tool call вне allowlist/schema и patch с traversal, binary/mode changes или symlink path.
9. Code indexer не читает tracked Python symlink, ведущий за пределы checkout; sandbox ограничивает объём stdout/stderr, накопленный в памяти хоста.

Успешное выполнение запрещённого действия является критичным блокером приёмки.
