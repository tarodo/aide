# Architecture Decision Records (ADRs)

This directory holds the ADRs for AIDE. An ADR captures a single architectural
decision, the forces that drove it, the alternatives considered, and the
consequences. If a decision shapes how future code is written or how new
developers should read the system, it belongs here.

## File naming

```
docs/adr/adr-NNN-kebab-case-title.md
```

Rules:

- **Prefix:** `adr-` (lowercase). Makes ADR files group together alphabetically
  in any file listing and prevents ambiguity with other `docs/` content.
- **Number:** three digits, zero-padded (`001`, `002`, …, `042`, `006`).
  Three digits give headroom (up to 999 ADRs) and keep lexicographic order
  consistent with numeric order.
- **Title:** short, lowercase, kebab-case. Nouns preferred (`deletion-strategy`,
  `error-handling`, `layered-architecture`). No date, no status in the filename.
- **Extension:** `.md`.

Examples:

```
adr-001-layered-architecture.md
adr-006-deletion-strategy.md
adr-042-event-bus-choice.md
```

Numbers are **never reused**. When an ADR is superseded, keep the file, mark it
`Superseded`, and link to the replacement.

## Statuses

| Status | Meaning |
|--------|---------|
| `Proposed` | Draft, open for discussion. No code should rely on it yet. |
| `Accepted` | Decision is in force. Code and reviews should follow it. |
| `Deprecated` | No longer recommended, but not actively replaced. |
| `Superseded` | Replaced by another ADR. Link the successor in the header. |

## Template

Use the structure below for every new ADR. Keep headings stable so a reader
can scan across ADRs without re-learning the layout.

```markdown
# ADR-NNN: Short Decision Title

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-XXX
**Date:** YYYY-MM-DD
**Deciders:** <roles or names who must sign off>

---

## 1. Context and Problem

What is the situation? What forces are at play? Why now?

## 2. Options Considered

### Option A: <name>

Description, implementation sketch, assessment table, pros, cons.

### Option B: <name>

Same structure.

## 3. Trade-off Analysis

Comparison across options. Name the key tension explicitly.

## 4. Recommendation

The chosen option and why.

## 5. Implementation Notes (optional)

Concrete rules, conventions, or caveats that flow from the decision.
Place canonical how-to-apply guidance here — not in commit messages or
wiki pages that will drift.

## 6. Consequences (optional)

What becomes easier. What becomes harder. What we'll need to revisit.
```

Omit any section that is genuinely empty — do not leave placeholder text.

## When to write an ADR

Write one when:

- Two or more reasonable options exist and you are picking one.
- The decision is **non-obvious from the code** — a new developer reading the
  repo would not be able to infer *why* it was done this way.
- The decision has cross-cutting impact (touches more than one package, layer,
  or team).

Do **not** write an ADR for:

- Library version bumps, dependency additions (use commits / changelog).
- Local refactors that do not change the project's architectural contract.
- Style / formatting choices (use `CLAUDE.md` conventions instead).

## Allocating the next number

1. `ls docs/adr/adr-*.md` — find the current highest number.
2. Take the next integer, zero-pad to three digits.
3. Commit the new ADR together with the index update below.

Historic numbering is not necessarily dense; gaps left by abandoned drafts are
fine and do not need to be backfilled.

## Index

| #   | Title | Status |
|-----|-------|--------|
| 001 | [Layered Architecture — Router → Service → UoW → Repository → Model](adr-001-layered-architecture.md) | Accepted |
| 002 | [Generic Base Classes — `BaseRepository[M]` and `GenericService[M, C, U, R]`](adr-002-generic-base-classes.md) | Accepted |
| 003 | [Unit of Work Pattern and Session Lifecycle](adr-003-unit-of-work.md) | Accepted |
| 004 | [Monorepo Layout and Schema Re-export Pattern](adr-004-monorepo-layout.md) | Accepted |
| 005 | [Error Handling — Code Registry + `AppException` Handler](adr-005-error-handling.md) | Accepted |
| 006 | [Deletion Strategy — Soft Delete vs Cascade Delete](adr-006-deletion-strategy.md) | Proposed |
| 007 | [Testing Strategy — Per-Layer Fixtures and Isolation](adr-007-testing-strategy.md) | Accepted |
| 008 | [Polymorphic Dataset — Joined Table Inheritance](adr-008-polymorphic-dataset.md) | Accepted |
| 009 | [Optimistic Locking via `row_version`](adr-009-optimistic-locking.md) | Accepted |

Keep this table sorted by ADR number and update it in the same commit that
adds or changes an ADR.
