# Оценка качества

## Принцип

Оценивается не убедительность текста, а воспроизводимый результат на зафиксированных данных, модели, параметрах и commit.

## Наборы

### Document set

`evals/document_golden.json` содержит 30 вручную сопоставленных с синтетическими документами вопросов: 26 answerable и 4 out-of-scope. Есть русские формулировки, опечатки, два multi-source вопроса и prompt-injection случай.

Версия набора фиксируется SHA-256 в отчёте. `evals/document_smoke.json` остаётся отдельным коротким smoke set. Устаревшие источники и полноценная semantic correctness оцениваются на следующих этапах; текущий golden set не покрывает эти свойства. Cross-project leakage проверяется отдельными PostgreSQL/HTTP/MCP security-тестами M4.

### Code set

Планируется 20–30 задач в `exchange-demo` с исходным commit и скрытыми acceptance tests: bug fix, небольшая feature, refactoring, API compatibility, test repair и cross-service change.

Eval-задачи нельзя использовать для fine-tuning.

## Сравниваемые конфигурации

1. LLM без RAG.
2. LLM + vector retrieval.
3. LLM + hybrid retrieval.
4. Hybrid retrieval + patch/test loop.
5. Optional grounded/critic mode.
6. Optional LoRA только после основного POC.

## Метрики

### Retrieval

Текущий runner измеряет Recall@5 по ожидаемым source и сохраняет retrieval sources для каждого кейса. Для code RAG позже добавятся repo/path/commit и Recall@10/@20. Security-тесты M4 отдельно проверяют отсутствие чужого проекта в citations и retrieval trace.

### Ответы

Baseline и RAG сравниваются на одних 30 кейсах по `task_success`, correct refusal и false refusal rate. Для answerable кейса success требует непустого ответа с ожидаемыми citations; для out-of-scope — отказа. Это **protocol success**, а не доказательство semantic correctness fake-модели.

Grounded path дополнительно проверяет существование `[N]`, диапазон ссылки и числа внутри процитированного evidence. Полная supported/unsupported claims разметка остаётся необходимой для реальной модели.

### Coding

- patch applies;
- build pass;
- hidden tests pass и pass@1;
- изменения существующих тестов;
- число repair iterations;
- доля принятых человеком diff.

### Производительность

- p50/p95 latency и time to first token;
- tokens/sec и queue time;
- VRAM/RAM;
- время полной coding-задачи.

## LLM-judge

LLM-judge не считается абсолютным источником истины. `evals/judge_calibration.json` содержит 6 ручных labels и намеренные ошибки simulated judge outputs. M3 проверяет parsing и расчёт agreement (4/6), а **не качество реального LLM-judge**. Поле `simulated_outputs=true` делает это ограничение явным. Калибровку реальной модели нужно повторить в M7. Детерминированные проверки предпочтительнее: существование citation, точное значение, компиляция и тесты.

## Фактический fake-provider прогон M3

CI на Python 3.11 и 3.13 дал одинаковый результат: baseline task success `0/30`, grounded RAG `29/30`, Recall@5 `25/26`, correct refusal `4/4`. False refusal rate на answerable кейсах — `1/26`; этот провал остаётся видимым в per-case artifact. Simulated judge agreement — `4/6`. Эти цифры проверяют контур и метрики, но не являются качеством реальной LLM.

## Протокол

1. Зафиксировать dataset version, model, quantization, prompts, parameters и commit.
2. Запустить baseline и новую конфигурацию на одинаковых задачах.
3. Сохранить сырые результаты без секретов.
4. Разобрать провалы по категориям: retrieval, grounding, reasoning, tool, sandbox, test.
5. Повторить критичные прогоны после исправлений.

## Критерии решения

До финального тестирования фиксируются конкретные пороги. Минимальные условия:

- нет успешных критичных ACL/sandbox нарушений;
- источники и отказы проверяемы;
- полный контур показывает согласованное заранее преимущество перед baseline;
- тестировщики проходят основные сценарии без помощи автора;
- фактические ограничения и стоимость эксплуатации документированы.

Решение относится к production-пилоту, а не к немедленному критичному production.
