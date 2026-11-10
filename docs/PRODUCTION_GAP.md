# Что отделяет POC от enterprise-пилота

POC проверяет базовую форму решения на синтетических данных. Enterprise-пилот допустим только после измерений, security review и ограниченного допуска пользователей. Критичный production — отдельное решение за рамками этого проекта.

| Область | Сейчас | Нужно перед ограниченным пилотом |
|---|---|---|
| Модель | Provider написан; модель на целевом GPU не запускалась | Выбрать модель/квантизацию измерениями; закрепить версии, параметры и rollback |
| Retrieval | PostgreSQL full-text + pgvector; embeddings fake, reranker не подключён | Локальные embeddings, повторная индексация, multilingual/code retrieval eval, reranker только по измеримому эффекту |
| Качество coding | Три синтетические задачи и scripted fake HTTP | Расширенный benchmark с независимыми acceptance tests и human review labels |
| Identity | Локальные admin/viewer tokens | SSO/OIDC, user/group lifecycle, отзыв credentials и аудит административных действий |
| Tenant isolation | Project membership и SQL ACL в POC | Threat model реальных проектов, тесты на cross-project/cache leakage, проверка repository-level ACL |
| Sandbox | Docker container с ограничениями | Изолированные workers, усиленный runtime (VM/gVisor/Kata), проверка escape/resourcing и уборки |
| Масштаб | Один локальный хост; capacity не измерена | Очереди и quotas, load/failure tests, capacity planning для конкретных задач и моделей |
| Надёжность | Нет заявленных SLO и HA | Backup/restore, мониторинг/alerts, incident response и rollback |
| Поставка | CI проверяет код; runtime модели ещё не закреплён | Внутренний artifact/model registry, pinned images, hashes/SBOM и управляемые обновления |
| Управление изменениями | Diff ждёт человека; merge агентом отсутствует | Protected branches, code owners, обязательные CI и обычный human approval |
| Данные и логи | Prompt/response не пишутся по умолчанию в audit | Согласовать retention, deletion, audit access и правила логирования компании |

## Реальные ограничения на сегодня

- POC использует синтетические документы и `exchange-demo`, не репозитории биржи.
- Зелёный CI подтверждает тестовые контракты, не качество локальной модели.
- Fake embeddings не подтверждают семантический vector search.
- Три задачи не дают статистически значимой оценки полезности или pass@1.
- Docker limits не являются полной защитой от container escape.
- Возможности на 100 разработчиков, общие GPU узлы и высокую доступность нельзя выводить из локального запуска.

## Условия перехода

1. Закрыть M7 на целевом ПК: модель, embeddings, offline, фактические метрики.
2. Пройти M8: одинаковые сценарии 2–3 тестировщиков, ошибки и human acceptance.
3. Провести threat modeling и отдельный security/architecture review для выбранной схемы.
4. Начать только небольшой изолированный пилот с ограниченным набором repositories и пользователей.
5. Не добавлять production credentials, критические репозитории или права на merge до отдельного одобрения следующего этапа.

Подробный пайплайн и целевая схема описаны в [PRODUCT_OVERVIEW.md](PRODUCT_OVERVIEW.md); инженерные этапы — в [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).
