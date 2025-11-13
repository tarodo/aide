# ADR-0002: Service-Repository and Unit of Work Patterns

- **Status:** Accepted
- **Date:** 2025-11-08
- **Deciders:** @backend-team

## Context and Problem Statement

As the application's complexity grows, we need a clear and maintainable architecture for handling business logic and data persistence. A simple, monolithic API endpoint structure where business logic, data access, and HTTP handling are mixed becomes difficult to test, maintain, and reason about.

The key goals are:

1.  **Separation of Concerns:** Isolate business logic from data access details and the presentation layer (API).

2.  **Transactional Integrity:** Ensure that a single business operation either completes fully or not at all (atomicity).

3.  **Testability:** Enable unit testing of business logic without requiring a live database connection.

4.  **Maintainability:** Create a predictable structure that is easy for developers to understand and extend.

## Considered Options

### 1. Active Record Pattern

- **Description:** The model objects themselves contain methods for persistence (e.g., `user.save()`, `user.delete()`). This pattern is common in frameworks like Ruby on Rails.

- **Pros:**
    - Simple and quick for basic CRUD operations.
    - Easy for developers to learn initially.

- **Cons:**
    - Violates the Single Responsibility Principle, as models are responsible for both their state and their persistence.
    - Tightly couples business logic to the persistence framework (e.g., SQLAlchemy).
    - Makes unit testing difficult, as business logic calls database methods directly.
    - Managing transactions across multiple objects can become complex and explicit.

### 2. Service Layer with Repository and Unit of Work (UoW) Patterns

- **Description:** A layered architecture with three distinct components:

    - **Service Layer (`services/`):** Contains the application's business logic. It orchestrates data operations but does not know how they are persisted.

    - **Repository Layer (`repositories/`):** An abstraction over the data store. It provides a collection-like interface for accessing domain objects (e.g., `users.get_by_id()`, `users.add()`), hiding the underlying ORM/SQL details.

    - **Unit of Work (`db/uow.py`):** Manages transactions. It tracks all changes made during a business operation and commits them atomically to the database upon success, or rolls them back on failure. It also acts as a factory for repositories, ensuring they all share the same database session/transaction.

- **Pros:**
    - **Excellent Separation of Concerns:** Each layer has a clear responsibility.

    - **High Testability:** Services can be tested by mocking the repository/UoW layer, completely isolating business logic from the database.

    - **Transactional Integrity:** The UoW pattern provides a robust and implicit way to manage transactions, typically via a context manager (`with uow:`).

    - **Flexibility:** The persistence mechanism can be changed with minimal impact on the business logic by simply implementing new repositories.

- **Cons:**
    - **More boilerplate:** Requires creating separate classes for services, repositories, and the UoW, which can feel like more upfront work for simple applications.

    - **Steeper learning curve:** Developers need to understand the roles of all three patterns.

## Decision Outcome

**Chosen option:** "Service Layer with Repository and Unit of Work (UoW) Patterns".

This combination of patterns provides a robust, scalable, and maintainable architecture that directly addresses all our goals. The clear separation of concerns and improved testability are critical for the long-term health of the project. While it involves more initial setup, the benefits in terms of code quality, maintainability, and developer productivity far outweigh the costs.

The implementation is as follows:

- **Services (`backend/services/`)** are injected into API endpoints and contain all business logic.

- **Unit of Work (`backend/db/uow.py`)** is used as a context manager within service methods to ensure transactional atomicity.

- **Repositories (`backend/repositories/`)** are accessed via the UoW instance (e.g., `uow.users`) and handle all data access using SQLAlchemy.

### Consequences

- **Positive:**
    - The codebase is highly structured and predictable.
    - Business logic is decoupled from persistence and is easily unit-testable.
    - All database operations within a service call are guaranteed to be atomic.

- **Negative:**
    - Adds a layer of abstraction that can increase the number of files and classes in the project.

- **Impact:**
    - All new business logic and data access must follow this pattern.
    - Developers need to be familiar with these concepts.

