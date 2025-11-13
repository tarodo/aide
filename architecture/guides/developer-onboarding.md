# Developer Onboarding Guide

Welcome to the team! This guide provides the essential steps and resources to get you started with the project.

## 1. First Steps

1.  **Project Overview:** Start by reading the main project `README.md` in the root directory. It provides a high-level overview of the project's purpose and goals.

2.  **Local Setup:** Follow the instructions in the `README.md` to set up your local development environment using Docker and `make`. The `make up` command is your starting point.

3.  **Explore the Code:** Familiarize yourself with the project's directory structure, as described in the main `README.md`.

## 2. Understanding the Architecture

To get a quick grasp of how the system is designed, review the architectural documentation in the following order:

1.  **Start with the Big Picture:** Read the [Architecture README](./../README.md) for an overview of how the documentation is structured.

2.  **Visualize the System:** Look at the **[C4 Model diagrams](./../c4-model/)**. They provide a visual breakdown of the system from high-level context down to its internal components.
    -   [C1: System Context](./../c4-model/c1-system-context.md)
    -   [C2: Container Diagram](./../c4-model/c2-container.md)
    -   [C3: Components Diagram](./../c4-model/c3-components.md)

3.  **Understand Key Decisions:** Skim through the **[Architectural Decision Records (ADRs)](./../adr/)**. These documents explain the *why* behind our key technical choices. The most important ones to read first are:
    -   [ADR-0002: Service-Repository and Unit of Work Patterns](./../adr/0002-service-repository-uow-patterns.md) - This explains our core backend architecture.
    -   [ADR-0001: JWT-based Authentication](./../adr/0001-jwt-authentication-and-authorization.md)

4.  **Learn Common Patterns:** Read the **[Common Patterns Guide](./common-patterns.md)** to understand how to implement API endpoints and handle errors correctly.

## 3. Your First Task

A good first task is often to add a new field to an existing model, update its corresponding service and API endpoint, and add a test for it. This will give you hands-on experience with all layers of the application.

If you have any questions, don't hesitate to ask the `@backend-team`!

