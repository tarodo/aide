# AIDE Metastore — Roadmap, Open Work, and Positioning

**Date:** 2026-04-27
**Companion to:** [`2026-04-27-architecture-review.md`](./2026-04-27-architecture-review.md)

---

## 1. What is shipped and what is open

### 1.1 Backend / contract engine

| Phase | Spec | Plan | Code | Tests | Migrations | Status |
|-------|------|------|------|-------|------------|--------|
| Lineage Phase 1 (identity-level) | ✅ ADR-016 | ✅ | ✅ | ✅ | ✅ | **Shipped** |
| Lineage Phase 2 (tech-field templates) | ✅ ADR-017 | ✅ | ✅ | ✅ | ✅ | **Shipped** |
| Lineage Phase 3 (schema-pinned + origin enum + compat) | ✅ ADR-018 | ✅ | ✅ | ✅ | ✅ A+B | **Shipped** (`71e9139`) |

ETL pre-flight guide (`docs/integrations/etl-pre-flight.md`) published, SDK method `dataset_links.compat()` available, package versions 0.2.0 in lockstep.

### 1.2 Frontend

| Phase | Artifacts | Code | Status |
|-------|-----------|------|--------|
| Spec: Mantine SPA (535 lines) | ✅ | — | Spec approved |
| Roadmap (7 phases) | ✅ | — | Plan exists |
| Phase 1 — Foundation (auth shell, AppShell, MSW, types.gen) | ✅ detailed plan | — | **Not started** |
| Phases 2–7 (systems → datasets → fields/schemas → crawls → admin → hardening) | ✅ plans | — | **Not started** |

There is **no `frontend/` directory** in the repository. Ready to start immediately — no blockers identified (Node 20 LTS, pnpm 9 listed as prerequisites).

### 1.3 Branch hygiene

8 stale `claude/*` branches + 2 worktree branches. Not blocking, but worth a sweep at the next merge window.

---

## 2. Top-level roadmap (proposal)

```
NOW    ─┐
        ├─ M1: Operational hardening (CI/CD, health, metrics, policies)   2–3 weeks
        ├─ M2: Frontend Phase 1 (auth + AppShell + MSW)                    2 weeks
        │
NEXT   ─┤
        ├─ M3: Frontend Phases 2–4 (systems / datasets / fields)           4–6 weeks
        ├─ M4: Compat webhooks / push notifications                        1 week
        ├─ M5: Bulk-compat optimization (batched scoring)                  1 week
        │
LATER  ─┤
        ├─ M6: Frontend Phases 5–7 (crawls / admin / polish)               3–4 weeks
        ├─ M7: RBAC / multi-tenancy                                         3 weeks
        ├─ M8: HA deployment (Helm chart, Patroni/RDS, secret store)       3 weeks
        ├─ M9: OpenLineage adapter (runtime lineage import)                 2 weeks
        ├─ M10: dbt / Airflow / Spark connectors                            3 weeks
        └─ M11: Data quality hooks (assertions, contracts as tests)         3 weeks
```

Numbers are rough order-of-magnitude estimates, not commitments.

---

## 3. Idea assessment in modern data engineering

### 3.1 Where AIDE sits on the map

Class — **decentralized data contract registry / metastore** with a focus on **pre-flight contract validation**. Neighbors on the market:

| Product | Focus | Where AIDE differs |
|---------|-------|---------------------|
| **DataHub** (LinkedIn) | discovery, lineage, governance | AIDE is much lighter, no graph DB, no Kafka bus; stronger on source/target contract |
| **OpenMetadata** | governance + lineage UI | AIDE is declarative, no runtime collectors |
| **Apache Atlas** | enterprise governance | Atlas is Hadoop-era; AIDE is modern stack |
| **Marquez / OpenLineage** | runtime lineage events | AIDE declares the contract **before** a run, OL describes it **after** — complementary |
| **Confluent Schema Registry** | Avro/JSON Schema for Kafka | AIDE is multi-system, not tied to one format |
| **Unity Catalog** (Databricks) | governance inside the lakehouse | AIDE is vendor-agnostic, self-hosted |
| **dbt + dbt-contracts** | model-level contract inside dbt | AIDE works above any pipeline, not only dbt |

### 3.2 Strengths of the idea

1. **Contract-first**: pre-flight `compat` endpoint — a real need for teams whose ETL silently breaks in production from schema drift.
2. **Schema pin + origin enum**: three-state lifecycle (`mapped`/`tech`/`deprecated`) — covers the real case of backward-compat columns, which most catalogs cannot model.
3. **Polymorphic datasets**: a single model for RDBMS/Kafka/S3/Hive/SFTP — most competitors keep these split.
4. **Cross-system cast rules** — a bridge for cross-engine typing (SQL ↔ Avro ↔ Parquet ↔ JSON Schema). Cast standardization is an underrated pain.
5. **Drift separated from breakage**: `warn` (needs refresh) ≠ `error` (do not load). Most catalogs conflate the two.
6. **Lockstep SDK + Crawler**: operators get clients out of the box — no need to write wrappers.

### 3.3 Weaknesses for production use

1. **Declarative lineage only**: does not build lineage from runtime events. Without an OpenLineage adapter — does not answer «where the data actually came from».
2. **No data quality**: the contract describes **types**, not **values** (no nulls < X%, distinct count, freshness). A real data contract includes those.
3. **No discovery UI**: nothing for an analyst to look at until the frontend ships.
4. **No dbt/Airflow/Spark integrations**: broad adoption needs adapters that auto-sync the catalog.
5. **No RBAC**: only authn. Multi-tenancy is not in the schema.
6. **No push for compat**: poll-only. Acceptable for k8s CronJob ETL workers, not for real-time.
7. **Single-region, single-PG**: scale ceiling.

### 3.4 Where AIDE will be useful in production

**Good fit:**

- Teams of 5–50 engineers with 3–10 stores (PG, ClickHouse, Kafka, S3) and 50–500 pipelines.
- Boring-stack ETL without a vendor catalog; need self-hosted and vendor-agnostic.
- Pain point is silent schema drift (column type changed → pipeline broke at 4am).
- Distinct source-owner / target-owner roles, need an explicit contract between them.
- Acceptable to architect «ELT through pre-flight» (the worker asks AIDE before load).

**Bad fit:**

- Real-time event-driven with millions of schemas/hour — Schema Registry / OpenMetadata fit better.
- Large enterprises with governance demands (PII classification, lineage UI, business glossary) — DataHub / OpenMetadata.
- Pure Databricks/Snowflake stacks — native catalogs integrate better.

### 3.5 What will add value after development

Priority 1 (without these, production value is limited):
- **Frontend MVP** — without a UI the value to analysts is zero.
- **OpenLineage import** — lets the declarative contract be enriched with runtime data.
- **/metrics + /health** + CI/CD — required to ship at all.
- **RBAC** — without it, single-team only.

Priority 2 (expands the market):
- **dbt adapter** — model sync.
- **Data quality hooks** — `compat` extends to value-level checks.
- **Webhooks** — push drift notifications to Slack/Teams.

Priority 3 (maturity):
- **Helm chart + HA-PG**.
- **Vault / AWS Secrets Manager integration** for CredentialRef.
- **GraphQL layer** for discovery.

---

## 4. Verdict

**The idea is solid and lands on a current trend** — *data contracts as code*. The schema-pin approach and three-state origin reflect real-world experience, not «MVP from a blog post».

**Architecture** is ahead of the frontend: the backend is ready for product growth, operational scaffolding lags behind.

**Production usefulness after development:** yes, for a niche but real segment (mid-size teams, vendor-agnostic stack, contract-driven ETL). Competition is fierce, but the position is defensible if invested in OpenLineage compatibility and a UI is shipped.

**Risks:**
- Without a UI and integrations (dbt, Airflow), it stays an internal tool of one team.
- Without OpenLineage, it will be perceived as «contract-only», not a full catalog.
- Without RBAC and HA, it will not pass enterprise due diligence.

**Recommendation:** close M1 (operational hardening) → start the frontend (M2–M3) in parallel → by M9–M11, take a strategic call: «stay a lightweight contract store» or «grow into a DataHub-lite catalog».

---

## 5. Documents for further work

- [`2026-04-27-architecture-review.md`](./2026-04-27-architecture-review.md) — architecture review and production readiness.
- `docs/superpowers/plans/2026-04-15-frontend-roadmap.md` — frontend plan.
- `docs/integrations/etl-pre-flight.md` — guide for ETL workers.
- `docs/adr/` — architectural decisions (18 records).
- `docs/AIDE_data_model.json` — ER diagram (ChartDB).
