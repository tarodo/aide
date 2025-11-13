# C3: Components Diagram

This diagram decomposes the **Backend API Container** into its major logical components, showing how they interact to handle an incoming API request.

```mermaid
graph TD
    subgraph "Backend API Container"
        A[API Endpoints <br> (FastAPI Routers)]
        B[Service Layer <br> (Business Logic)]
        C[Repository Layer <br> (Data Access)]
        D[Unit of Work <br> (Transaction Management)]
        E[Domain Models <br> (SQLAlchemy ORM)]
    end

    user("User") -- "HTTPS Request" --> A
    A -- "Calls" --> B
    B -- "Uses" --> D
    D -- "Provides" --> C
    C -- "Manipulates" --> E

    subgraph "Database"
        DB[(PostgreSQL)]
    end

    E -- "Maps to tables in" --> DB
```

| Component | Description |
|---|---|
| **API Endpoints** | Receives HTTP requests, validates input using Pydantic schemas, and delegates to the Service Layer. Implemented as FastAPI `APIRouter`s. |
| **Service Layer** | Contains the core business logic of the application. Orchestrates operations, enforces rules, and uses the Unit of Work to interact with the database. |
| **Unit of Work (UoW)** | Manages the lifecycle of a database transaction. It provides repositories with a shared session and ensures that all operations within a service call are committed or rolled back atomically. |
| **Repository Layer** | Abstracts the data persistence mechanism. Provides a clean, domain-centric API for the Service Layer to query and persist Domain Models, hiding the specifics of SQLAlchemy. |
| **Domain Models** | Represents the application's core entities (e.g., User, System, Dataset) as SQLAlchemy ORM classes. These objects are the primary data carriers within the backend. |

