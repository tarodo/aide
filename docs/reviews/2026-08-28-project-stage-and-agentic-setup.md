# AIDE Metastore — Стадия проекта и агентная инфраструктура

**Дата:** 2026-08-28
**Ветка:** `main` @ `b28b51d` (последний коммит 2026-04-30 — 4 месяца без изменений)
**Предшественники:** [`2026-04-27-architecture-review.md`](./2026-04-27-architecture-review.md); ревью от 2026-07-02 на ветке `origin/review/2026-07-pilot` (не слита) — его находки по коду перепроверены, его продуктовый сценарий (пилот) здесь не используется.
**Метод:** 27 агентов — 7 измерений аудита + построчный аудит CLAUDE.md + охота за недокументированными gotcha; 14 critical/high находок прошли adversarial-верификацию (critical — 2 голоса, high — 1): 14/14 подтверждены, 3 скорректированы в формулировках. Линтеры и все три тест-сьюта прогнаны фактически.

---

## 1. Вердикт: стадия

**Технически — «зрелый бэкенд-MVP в заморозке».** Ядро (домен, слоистая архитектура, миграции, тесты) на уровне late-alpha/early-beta продукта; обвязка (деплой, безопасность чтения, CI, UI) — на уровне прототипа. С 30 апреля код не менялся.

| Что подтверждено запуском | Результат |
|---|---|
| `ruff check .` / `black --check .` | зелёные |
| `mypy .` | 2 известные ошибки (`_seed_core.py:8`, `sdk/.../datasets.py:9`) — `make check` всегда красный |
| `make test-docker` | **631 passed, 0 failed, 91 % coverage**, 2 мин 20 с |
| `sdk/tests`, `crawler/tests` | 15 + 109 passed |

| Измерение | Апрель | Июль | Сейчас | Комментарий |
|---|---|---|---|---|
| Архитектура бэкенда | 9 | 7 | **6.5** | Ядро не деградировало, но два новых сервиса (`lake_sync`, `dataset_link_compat`) обходят репозитории; `repositories/base.py` импортирует из `api/` (инверсия слоёв); 4 копии CRUD-lifecycle |
| Тесты | 8 | 7 | **6.5** | 755 зелёных тестов, но 23 копии auth-фикстур, 18 копий `_MockUnitOfWork`, coverage без конфигурации, единственный gate — неустановленный pre-commit |
| SDK / crawler как продукты | — | 4 | **3.5** | `update()` шлёт PUT в PATCH-only роуты (405), `create_many` на 9 ресурсах без `/batch`, 7 роутеров без обёртки, транспорт без тестов |
| Безопасность и ops | 6 | 5/3 | **4** | Анонимное чтение каталога, нет prod-образа, `/health`, backup; bootstrap сбрасывает пароль суперпользователя при каждом старте |
| Документация | 9 | 6 | **5.5** | ADR и `docs/integrations` точные; README описывает продукт до lineage (6/20 роутеров нет), версии 0.1.0 / 0.3.0 / v0.3.0-base несогласованы |
| Гигиена репо / agentic-dev | — | — | **4.5** | Нет CI, LICENSE, `.dockerignore`; `.claude/` целиком в `.gitignore`; 15 слитых веток + 3 worktree; 51 % коммитов нарушают правило ≤50 |
| AI-навигируемость кода | — | — | **7** | 207 файлов / 14.7k LOC, 19 сущностей с единым stem; сложность в 10 сквозных модулях и трёх функциях по 140–270 строк |

---

## 2. Ключевые находки

### Подтверждённые блокеры production-готовности (из июльского ревью, без изменений)
- **Анонимное чтение каталога** — все list/detail/tree/compat роуты, включая `/credential-refs` с Vault-путями; гейтированы только `/users` (`backend/api/v1/utils/crud_router.py:63-70`). Фикс — два дефолта в `crud_router` + `Depends(get_current_user)` на ~18 ручных GET; только 4 теста ходят без заголовков.
- **Crawler поддерживает только PostgreSQL** — `type_map` без dialect-веток, один неизвестный тип валит весь crawl (`crawler/aide_crawler/type_map.py`). Станет блокером при первом не-PG источнике.
- **Нет deployable-артефакта** — единственный Docker target dev/root/`--reload`, `COPY . .` без `.dockerignore`; compose форсит `ENV=dev`, что выключает валидатор секретов (`Dockerfile`, `docker-compose.yml:8`, `backend/core/settings.py:53-56`).
- **render-sql кастует всё в `string`** — `EngineRenderService` берёт тип из `Field.extra["data_type_code"]`, который заполняют только тесты; `link.target_schema_id` не читается (`backend/services/engine_render_service.py:88-90`). Фича engines на production-пути не работает.
- Нет `/health`, `/ready`, healthcheck и restart policy; нет backup-процедуры; нет CI.

### Новое относительно июля
- **SEC-N1** — `_ensure_initial_superuser` при каждом старте перезаписывает пароль, `is_active`, `is_superuser`, `full_name` значениями из env (`backend/services/user.py:98-100`). Отключить bootstrap-аккаунт невозможно.
- **SEC-N2** — нет user-lifecycle API: деактивация, смена пароля, отзыв чужих refresh-токенов только через SQL.
- **SEC-N3** — bcrypt 5.0 бросает исключение на пароль > 72 байт → 500 на логине и создании пользователя.
- **SDK-CRW-R02** — `BaseResource.update` → PUT; `datasets`/`engines`/`dataset-links`/`field-links`/`tech-field-templates` принимают только PATCH → 405. В репо вызовов нет, поэтому не замечено.
- **BA-02** — `UnitOfWork.__aexit__` не закрывает сессию, если `commit()`/`rollback()` бросил (`backend/db/uow.py:60-65`).
- **BA-06** — `EnvelopeResolver` op/ts/before-пути мёртвые: рендереры выдают только after-image проекции; Spark и Impala рендереры побайтово идентичны.
- **Пул соединений** — `create_async_engine(DATABASE_URL)` без `pool_pre_ping`/таймаутов: после рестарта PG приложение отдаёт 500 до цикла пула.
- **Retention** — `refresh_tokens` растёт вечно (`delete_expired` без вызова), `crawl_runs` не чистится; ADR-006 требует purge-job, его нет.
- **Зависимости** — 60 из 91 пакетов отстают, lock от 2026-04-28; нет dependabot/pip-audit. Живых CVE нет (ecdsa 0.19.2 не задействован — HS256).
- **Тесты** — единственный gate — pre-commit, гоняющий полный Docker-сьют на каждый коммит (включая docs-only), и он не установлен в `.git/hooks`.
- **Документация** — все 5 spec'ов «Draft (awaiting review)» при 4 слитых; ADR-006 «Proposed» с контекстом «deleted_at нет» через 4 месяца после внедрения; ADR-016 ссылается на удалённый `is_tech` без указателя на ADR-018.

---

## 3. CLAUDE.md: аудит и переписывание

Старый файл: 169 строк, оценка **62/100** (commands 13/20, architecture 16/20, non-obvious 10/15, conciseness 6/15, currency 7/15, actionability 10/15).

Проблемы: ~40 % текста дословно дублировали ADR-006/010/011/014/018/019 и `docs/integrations/lake-sync.md`; 6 устаревших/ложных утверждений (`.env` вместо `backend.env`; «SDK contract relies on `details`» — SDK его не читает; `_seed_core.py` как образец `type: ignore` — единственный модуль *без* него; `sortable` вместо `sortable_fields` и несуществующий `assert`; «no `__all__`» при наличии в `batch.py`; список из 4 тест-директорий при 9); три заметки про один константу/одну миграцию; и, главное, **отсутствовали 14 gotcha с высокой уверенностью**, на которых агент реально спотыкается (локальный `pytest` сносит dev-БД через `downgrade base`; обязательный `downgrade()` в каждой миграции; PUT vs PATCH в SDK; обязательный `row_version`; регистрация репозитория в `UnitOfWork.__aenter__`; unmapped error code → 500; rate-limit логина 5/мин ловит тесты; `%:` catch-all в Makefile; порядок сидов; нереентерабельный UoW; корневой `.venv` без sdk/crawler; `autoflush=False`; порядок в `GENERIC_TYPE_MAP`; разные auth-дефолты у двух стилей роутеров).

Новый файл: ~100 строк. Принципы (официальная guidance Anthropic + writing-for-agents): только то, что нельзя вывести из кода за 30 секунд; каждая конвенция — одна строка с указателем на ADR; никаких эндпоинт-семантик (они в `docs/integrations`); карта сквозных модулей вместо ASCII-дерева; чек-лист «добавить сущность» дополнен `uow.py` и `ERROR_MAP`; правило коммитов без caveman.

---

## 4. Агентная инфраструктура: что добавлять, а что нет

### Graphify — не сейчас
Репозиторий маленький и регулярный: 207 файлов, 14.7k LOC, 19 сущностей с единым stem по 7 слоям, фан-ин сосредоточен в 6 явных хабах (`core.exceptions`, `db.uow`, `core.security`, `core.errors`, `repositories.base`, `models.dataset`), фан-аут — в двух списках-проводках (`main.py`, `uow.py`). Агент достигает ~85 % кода паттерн-матчингом по чек-листу из CLAUDE.md. Реальная сложность — внутри трёх функций по 140–270 строк (`lake_sync`, `dataset_link_compat`, `engine_render_service`), которые граф не упрощает. Таблица сквозных модулей в новом CLAUDE.md (10 строк) даёт тот же выигрыш при нулевом обслуживании; graphify же требует пересборки после изменений и коммита `graphify-out/` в репо. **Пересмотреть**, когда появится фронтенд (второй язык) или число файлов перевалит за ~500.

### Caveman — отказаться от плагина, оставить дисциплину
Факт: правило «≤50 символов, тело только при неочевидном why» исполнялось на 49 %; 90 % последних 60 коммитов без тела; информативны ровно те 10 %, где есть «why». Для `fix`/`refactor` без тела история теряет причину — это и есть цена ультра-сжатия. Ревью и планы проекта пишутся полными предложениями, поэтому сжатие *коммуникации* Claude тоже не нужно (Fable 5 и так лаконичен без потери точности). Замена: обычный Conventional Commits, subject ≤72 (стандарт git), тело с «why» для `fix`/`refactor`, без AI-трейлеров. Правило уже в новом CLAUDE.md; **глобальный `~/.claude/CLAUDE.md` всё ещё требует `caveman:caveman-commit`** — его нужно поменять вручную, иначе глобальное правило переопределит проектное.

### Что добавить (в порядке отдачи)
1. **CI (GitHub Actions)** — `make check` + `make test-docker` + `sdk/crawler` тесты на PR. Единственный работающий gate сейчас — ничего. Полдня.
2. **Хуки вместо инструкций** — по guidance Anthropic то, что «должно случаться всегда», делается хуком, а не строкой в CLAUDE.md: `PostToolUse` (Edit/Write `*.py`) → `ruff --fix` + `black` на файле; `commit-msg` хук (или `PreToolUse` на `git commit`) → проверка Conventional Commits и отсутствия `Co-Authored-By: Claude`. Тогда строки «run make format» и «no AI trailers» становятся принудительными.
3. **Сузить `.gitignore`** — ignore только `.claude/settings.local.json` и `.claude/worktrees/`; коммитить `.claude/settings.json` (хуки, allowlist), `.claude/rules/`, `.claude/skills/`. Сейчас никакая агентная конфигурация не версионируется.
4. **`.claude/rules/` с `paths:`** — вынести секцию Testing в `rules/testing.md` (`paths: tests/**`), правила миграций в `rules/migrations.md` (`paths: backend/alembic/**`), crawler-gotcha в `rules/crawler.md`. Они грузятся только когда Claude трогает эти файлы; CLAUDE.md ужимается до ~60 строк.
5. **Pre-commit** — установить (`pre-commit install`), убрать `pytest` из хуков (2 минуты Docker на docs-коммит), добавить `gitleaks`/`detect-secrets` (в истории уже был закоммиченный dev-JWT).
6. **Скиллы проекта** — `add-entity` (чек-лист из CLAUDE.md как исполняемый workflow), `new-migration` (gen → review drift → downgrade-check), `seed-all` (правильный порядок 4 сидов). Это ровно те многошаговые процедуры, которые guidance рекомендует выносить из CLAUDE.md в skills.
7. **Dependabot/Renovate + `pip-audit` в CI** — lock 4 месяца не обновлялся.
8. **`/doctor` раз в квартал** — Claude Code сам предлагает вырезать из CLAUDE.md выводимое из кода.
9. Гигиена одним sweep'ом: LICENSE, `.dockerignore`, `git branch -d` 15 слитых веток + `git worktree prune`, версия backend 0.1.0 → 0.3.0, ADR-006 → Accepted, статусы spec'ов.

---

## 5. Рекомендуемый порядок на ближайшие 2 недели

| Неделя | Задачи | Findings |
|---|---|---|
| 1 | CI; auth на чтение (`crud_router` дефолты + ручные GET); prod-stage Dockerfile + `.dockerignore` + `USER`; `/health` + `/ready`; fail-closed настройки (`ENV` без дефолта `dev`); LICENSE | D2, SEC-01, DEP-01/02/03, DEP-04, SEC-02, CP-6 |
| 2 | render-sql читает pinned-схему (BA-01); SDK `patch` + `details` + timeout; сузить `.gitignore` + хуки + `.claude/rules`; pre-commit без pytest; branch sweep; README endpoint-таблица и env-шаг | BA-01, SDK-CRW-R02/R03, HYG-01..05, DOC-01/02 |

Дальше — по продуктовому решению: новые источники для crawler (следующий диалект — L-эпик: драйвер + каталог типов + cast-правила), read-only UI, либо OpenLineage. Ни одно из них не блокирует работу над ядром.

---

## 6. Ссылки
- Claude Code: [Best practices](https://code.claude.com/docs/en/best-practices), [CLAUDE.md и `.claude/rules/`](https://code.claude.com/docs/en/memory)
- Graphify: [репозиторий](https://github.com/safishamsi/graphify), [plugin README](https://github.com/pleaseai/claude-code-plugins/blob/main/plugins/graphify/README.md)
- Caveman: [репозиторий](https://github.com/JuliusBrussee/caveman), [обсуждение на HN](https://news.ycombinator.com/item?id=47954746)
