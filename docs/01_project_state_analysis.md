# ADR: Анализ текущего состояния проекта AIDE Metastore v2

**Статус:** Proposed
**Дата:** 2026-04-06
**Автор:** Architecture Review

---

## 1. Обзор проекта

**AIDE Metastore v2** — централизованная система управления метаданными для корпоративных data-платформ. Предоставляет contract-first, API-driven слой для описания систем, датасетов, схем и правил преобразования типов.

### Технологический стек

| Слой | Технология |
|------|-----------|
| Язык | Python 3.13.9 |
| Фреймворк | FastAPI (>=0.120.4) |
| ORM | SQLAlchemy 2.0 (async) |
| База данных | PostgreSQL 17 |
| Аутентификация | JWT (HS256) + bcrypt |
| Логирование | structlog (JSON/console) |
| Пакетный менеджер | uv |
| Контейнеризация | Docker + docker-compose |

### Архитектурные паттерны

- **Service-Repository** — бизнес-логика изолирована от persistence-слоя
- **Unit of Work (UoW)** — транзакционная граница на уровне запроса
- **Generic CRUD** — `GenericService`/`BaseRepository` с TypeVar-дженериками
- **Dependency Injection** — через FastAPI `Depends()`
- **Async-first** — все операции неблокирующие

---

## 2. Метрики кодовой базы

| Метрика | Значение |
|---------|----------|
| Python-файлы (backend) | ~60 |
| Строки кода (backend) | ~2,300 |
| Доменные сущности | 13 |
| API-роутеры | 13 |
| Сервисы | 14 (GenericService + 13 доменных) |
| Репозитории | 14 (BaseRepository + 13 доменных) |
| Pydantic-схемы | 13 модулей (Create/Read/Update на каждую сущность) |
| Миграции Alembic | 8 |
| Тестовые файлы | 35 |
| Зависимости (production) | 11 |
| Зависимости (dev) | 9 |

---

## 3. Архитектура приложения

### Слои и поток данных

```
HTTP Request
    |
    v
[API Layer]          backend/api/v1/*.py        — роутинг, валидация, авторизация
    |
    v
[Service Layer]      backend/services/*.py      — бизнес-логика, pre-create/pre-update хуки
    |
    v
[Unit of Work]       backend/db/uow.py          — управление транзакциями
    |
    v
[Repository Layer]   backend/repositories/*.py   — доступ к данным, CRUD
    |
    v
[ORM Models]         backend/models/*.py         — SQLAlchemy-модели
    |
    v
[PostgreSQL]
```

### Ключевые компоненты

**GenericService** (`backend/services/base.py`):
- Типизированный CRUD с TypeVar-дженериками
- Хуки `_pre_create()` / `_pre_update()` для валидации в доменных сервисах
- Автоматическое заполнение `created_by` / `updated_by`
- Пагинация через `Page[T]`

**UnitOfWork** (`backend/db/uow.py`):
- Async context manager с автоматическим commit/rollback
- Все репозитории доступны как атрибуты (`uow.users`, `uow.datasets`, и т.д.)
- Одна транзакция на бизнес-операцию

**CRUD Router** (`backend/api/v1/utils/crud_router.py`):
- Генератор стандартных CRUD-эндпоинтов
- Уменьшает boilerplate для типовых сущностей

---

## 4. Аутентификация и авторизация

- **JWT токены** с алгоритмом HS256, время жизни 30 минут
- **OAuth2 Password Flow** через `/api/v1/login`
- **Два уровня доступа:** `user` (чтение) и `superuser` (полный CRUD)
- **Dependency-based авторизация:** `get_current_user()` / `get_current_superuser()`
- **Пароли:** хеширование через bcrypt

---

## 5. Обработка ошибок

Централизованный реестр ошибок (`backend/core/errors.py`):

- 25+ предопределенных кодов ошибок
- Каждый код маппится на HTTP-статус и detail-сообщение
- Глобальный exception handler конвертирует `AppException` в JSON
- `build_error_responses()` генерирует OpenAPI-документацию для ошибок

---

## 6. Логирование и мониторинг

- **structlog** — структурированное логирование с JSON (production) и console (dev) рендерерами
- **Request ID** — автоматическая привязка `X-Request-ID` к каждому запросу
- **Контекстные данные:** method, path, client IP, status code, process time (ms)
- Prometheus и мониторинг **не реализованы** (упомянуты только в README)

---

## 7. Инфраструктура

### Docker
- `docker-compose.yml`: app, db (PostgreSQL 17), db-test
- `Dockerfile`: только dev-таргет с hot-reload (uvicorn --reload)
- Автоматические миграции и создание superuser при старте

### Качество кода
- **Pre-commit hooks:** ruff (линтер), black (форматирование), mypy (типы), pytest (тесты)
- **Makefile:** `make up`, `make test-docker`, `make format`, `make check`

### Тестирование
- Session-scoped миграции через Alembic
- Per-test транзакционные фикстуры с auto-rollback
- Отдельная БД для тестов (PostgreSQL на порту 5433)

---

## 8. Выявленные проблемы

### КРИТИЧНО

| # | Проблема | Файл | Описание |
|---|---------|------|----------|
| 1 | JWT Secret захардкожен | `backend/core/settings.py:25` | Дефолтное значение `"a_super_secret_key_that_should_be_in_env"`. В production это позволит подделать любой токен. |
| 2 | CORS открыт для всех | `backend/core/settings.py:16` | `CORS_ORIGINS = ["*"]` позволяет запросы с любого домена. Риск CSRF-атак. |

### ВЫСОКИЙ ПРИОРИТЕТ

| # | Проблема | Описание |
|---|---------|----------|
| 3 | Нет CI/CD pipeline | Только локальные pre-commit hooks. Нет GitHub Actions или аналога. Код может попасть в main без проверок. |
| 4 | README расходится с кодом | Redis и Prometheus заявлены в README, но не реализованы. Вводит в заблуждение новых разработчиков. |
| 5 | Нет production Dockerfile | Только dev-таргет. Нет multi-stage build, оптимизации размера образа, non-root user. |

### СРЕДНИЙ ПРИОРИТЕТ

| # | Проблема | Описание |
|---|---------|----------|
| 6 | `created_by`/`updated_by` без FK | Нет foreign key на таблицу `users`. Невозможно гарантировать referential integrity для аудита. |
| 7 | Нет health check эндпоинта | Отсутствует `/health` или `/readiness` для оркестратора (Kubernetes, ECS). |
| 8 | Нет rate limiting | Отсутствует защита от DDoS/brute-force на `/login`. |
| 9 | Дублирование двух PostgreSQL драйверов | Установлены и psycopg, и psycopg2-binary, и asyncpg одновременно. |

### НИЗКИЙ ПРИОРИТЕТ

| # | Проблема | Описание |
|---|---------|----------|
| 10 | Нет soft delete | Удаление записей необратимо. Нет поля `deleted_at` для мягкого удаления. |
| 11 | Отсутствует API versioning strategy | Только `/api/v1`, нет плана миграции на v2. |
| 12 | Нет OpenAPI metadata | Отсутствуют описания тегов, общая информация о API. |

---

## 9. Сильные стороны

1. **Чистая архитектура** — четкое разделение на слои с минимальным coupling
2. **GenericService** — эффективное переиспользование CRUD-логики через дженерики
3. **Async-first** — все операции неблокирующие, готовность к нагрузке
4. **Централизованная обработка ошибок** — единообразные ответы, автогенерация OpenAPI-документации
5. **Хорошая документация** — C4-диаграммы, ADR, developer guides, data model docs
6. **Структурированное логирование** — request ID tracking, JSON-формат для production
7. **Полиморфные датасеты** — гибкая модель для 5 типов источников данных
8. **Параметрическая система типов** — мощный механизм cross-system type mapping

---

## 10. Резюме

Проект имеет **хорошую архитектурную основу**, но находится на **ранней стадии** разработки. Основные риски связаны с безопасностью (JWT secret, CORS) и отсутствием production-инфраструктуры (CI/CD, Docker, мониторинг). Перед добавлением новой функциональности необходимо устранить критические проблемы безопасности и наладить pipeline.
