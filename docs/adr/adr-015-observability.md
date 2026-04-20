# ADR-015: Observability — `structlog` + Request-ID Middleware + Slow-Query Log

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

An operator has to answer four recurring questions while AIDE is
running:

1. **"What happened during this request?"** — given a
   user-reported error or a 4xx/5xx in a dashboard, find every log
   line produced while handling that request, including the SQL
   statements issued on its behalf.
2. **"What is this user/session doing?"** — correlate a sequence of
   requests from one client (UI session, crawler run).
3. **"Is a particular query pathological?"** — surface slow SQL so
   that it can be indexed, paginated, or refactored before it shows
   up in a page-latency dashboard.
4. **"Can I ingest these logs into our aggregator?"** — the output
   must be machine-parseable for whatever log pipeline (Loki, ELK,
   CloudWatch, Splunk) the environment actually uses.

We also need to decide what we are **not** building: APM traces,
per-user telemetry, custom metrics pipelines. The observability
posture must make explicit where the boundary is, because the cost
of adopting an APM is ongoing (SDK updates, spans to maintain,
another vendor to audit) and only pays off under specific workloads.

## 2. Options Considered

### Option A: Structured logging via `structlog` + request-id contextvars + slow-query warnings — **chosen**

- **Structured logger.** `structlog` configured once in
  `setup_logging()`; two renderers (JSON for production, colourised
  console for dev); `structlog.contextvars.merge_contextvars` runs as
  a processor so anything bound to the context is attached to every
  log record produced while that context is active.
- **Request correlation.** A single FastAPI HTTP middleware
  (`logging_middleware`) runs before any route, reads the
  `X-Request-ID` header (or generates a UUID if absent), and binds
  `{request_id, user_agent, referer}` via
  `structlog.contextvars.bind_contextvars`. The middleware logs
  `Request started` / `Request finished` / `Request failed` and
  echoes the request id back on the response header.
- **Slow-query warning.** `BaseRepository._execute` wraps
  `session.execute` with a `time.perf_counter` timer; if the elapsed
  time crosses `settings.SLOW_QUERY_THRESHOLD_MS` (default 500 ms)
  the repository logs a structured warning (`duration_ms`, `table`,
  `method`) that inherits the request id from the context.
- **Error envelope.** The global `AppException` and fallback
  `Exception` handlers include the `request_id` from contextvars in
  the `ErrorResponse` body (ADR-005), so a client-side 500 arrives
  with the id an operator needs to grep.
- **No APM.** No OpenTelemetry, no Sentry, no vendor SDK. Logs are
  the integration surface; the environment's log pipeline owns
  ingestion.

| Dimension | Assessment |
|-----------|------------|
| Per-request correlation | **Native** via `contextvars` |
| Code intrusion | **Minimal** — one middleware, one logger, one `_execute` wrapper |
| Dev ergonomics | **Good** — console renderer with colours for local runs |
| Machine parseability | **High** in prod — one JSON document per line |
| Vendor lock-in | **None** |
| Cost to add a new log line | **One `logger.info(...)` call** — context attaches automatically |

**Pros:**

- `structlog` with a `contextvars` processor means a log line emitted
  from *any* layer (router, service, repository) inherits the
  request id without the caller threading it through function
  signatures. The auth dependency, the rate limiter, the polymorphic
  dataset service — all emit correlated records.
- One JSON document per line is the common denominator that every
  log aggregator parses out of the box. The prod pipeline does not
  need a custom parser.
- The slow-query hook sits at the single entry point that
  `BaseRepository` and `SoftDeleteRepository` use for `SELECT` and
  count queries (`_execute`). Adding coverage is "use the helper";
  missing coverage is visible as a direct `session.execute(...)`
  call in code review.
- Dropping an APM in later is additive: OpenTelemetry can consume
  structlog's output, and a contextvar for `trace_id` can be added
  alongside `request_id` if and when an APM is adopted.

**Cons:**

- Without an APM, latency analysis across layers is a log-query job
  (group by `request_id`, order by timestamp). For steady-state
  observability this is adequate; for deep debugging of tail latency
  it is clumsy.
- `structlog.contextvars` is async-task-local, not thread-local. Any
  background job that forks out of the request context (spawning a
  `asyncio.Task` without propagating contextvars) loses the id
  silently. We do not do this today; if we ever do, the fork point
  has to re-bind.
- `_execute` covers SELECT and count paths; direct
  `uow.session.execute(...)` calls inside service hooks (used for
  ad-hoc dependent-entity counts — see ADR-001 §5) do **not** go
  through it and therefore do not participate in the slow-query
  threshold.

### Option B: Plain stdlib `logging` only (no structured frontend)

**Pros:** zero extra dependency; familiar formatter syntax.
**Cons:** extra context (request id, user, timings) turns into
free-form string interpolation; log aggregators need custom regex
per log line; contextvars integration is possible but hand-rolled.

### Option C: Full APM (OpenTelemetry + Sentry / Datadog)

Adopt OTel spans at every layer plus a hosted APM backend.

**Pros:** flame graphs, auto-instrumentation for FastAPI and
SQLAlchemy, error aggregation out of the box.
**Cons:** ongoing vendor cost; SDK drift concerns; another
dependency surface to audit; not justified at the current traffic
volume; the "where did my log lines go?" debugging story is
harder, not easier, for developers.

### Option D: Custom metrics pipeline (Prometheus exporter + Grafana)

Instrument the app with counters and histograms.

**Pros:** per-endpoint latency histograms; Grafana-friendly.
**Cons:** metrics do not replace logs for debugging a single
request; we would still need Option A for correlation; two pipelines
to maintain for marginal benefit over well-structured logs.

### Option E: Tracing-only (W3C Trace-Context propagation, logs carry `trace_id`)

Propagate W3C `traceparent` headers through the service and stamp
logs with `trace_id` instead of `request_id`.

**Pros:** future-compatible with any OTel collector.
**Cons:** the W3C header rarely arrives at our edge today; writing
a trace id without a trace aggregator to display it is a sunk cost;
`request_id` is already adequate correlation for our current
debugging needs.

## 3. Trade-off Analysis

The tension is **fidelity vs. operational weight**. Option C buys
the most fidelity (traces, spans, error grouping) at the highest
ongoing cost. Option A buys the correlation and slow-query
visibility that cover the real debugging needs with a minimal
dependency footprint. Options B, D, and E each address a slice of
the need but leave gaps that Option A closes.

We accept that Option A is deliberately below "modern observability
best practice" in a large-scale production sense; the project's size
and traffic do not justify more, and moving up (adding APM) is
additive rather than a rewrite.

## 4. Recommendation

Adopt Option A. Structured logging with request-id contextvars and a
slow-query warning at the repository layer is the baseline. Adding
APM is a future decision, not a current one.

## 5. Implementation Notes

### File map

| File | Role |
|------|------|
| [`backend/core/log_conf.py`](../../backend/core/log_conf.py) | `setup_logging()` — structlog configuration |
| [`backend/core/settings.py`](../../backend/core/settings.py) | `LOG_LEVEL`, `LOG_RENDERER`, `REQUEST_ID_HEADER`, `SLOW_QUERY_THRESHOLD_MS` |
| [`backend/main.py`](../../backend/main.py) | `logging_middleware` — binds request context, logs lifecycle events; global exception handlers stamp `request_id` into error envelopes |
| [`backend/repositories/base.py`](../../backend/repositories/base.py) | `BaseRepository._execute` — slow-query timer + warning |

### Logger configuration

[`backend/core/log_conf.py`](../../backend/core/log_conf.py) runs
once at import time from `main.py`. Shared processors:

- `structlog.contextvars.merge_contextvars` — the line that makes
  request correlation free.
- `structlog.stdlib.add_logger_name` / `add_log_level` / ISO
  timestamp / stack info / unicode decoder.

Renderer is chosen by `settings.LOG_RENDERER`:

- `json` (production) — `structlog.processors.JSONRenderer()` —
  one line per record, keys: `event`, `timestamp`, `level`,
  `logger`, plus every bound contextvar and every kwarg passed to
  the log call.
- `console` (dev default) — `structlog.dev.ConsoleRenderer(colors=True)`.

`logging.basicConfig(format="%(message)s")` routes stdlib log
records through structlog (other libraries' logs are formatted the
same way). `uvicorn.access` is explicitly muted because our HTTP
middleware already emits a richer `Request finished` record for
every request.

### The request middleware

[`backend/main.py:122-158`](../../backend/main.py:122):

```python
@app.middleware("http")
async def logging_middleware(request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get(settings.REQUEST_ID_HEADER, str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        user_agent=request.headers.get("user-agent"),
        referer=request.headers.get("referer"),
    )

    start_time = time.perf_counter()
    logger.info("Request started", http_method=..., http_path=..., client_host=...)

    try:
        response = await call_next(request)
        response.headers[settings.REQUEST_ID_HEADER] = request_id
        process_time = time.perf_counter() - start_time
        logger.info("Request finished", status_code=..., process_time=...)
        return response
    except Exception as exc:
        process_time = time.perf_counter() - start_time
        logger.error("Request failed", exc_info=exc, process_time=...)
        raise
```

Key rules:

- `clear_contextvars()` at the top guards against leakage between
  requests in the same asyncio task.
- `bind_contextvars` attaches `request_id` to every log record
  produced further down the call tree, across routers, services,
  repositories, and the exception handlers.
- The request id is **echoed on the response** via the same header
  the client may have sent. A client reporting an error can quote
  the header value; operators can grep `request_id=<value>` in the
  aggregator and see every line the server produced for that call.

### Request-id handoff — incoming / outgoing

- **Incoming:** trust the value in `X-Request-ID` if the client
  sent one. This lets a UI generate the id, log it client-side, and
  correlate with the server. A malicious client can, in principle,
  forge the id; we accept this — the id is a correlation handle,
  not an auth token, and the log aggregator's own timestamps and
  source IPs are the ground truth.
- **Outgoing:** the middleware always sets the header on the
  response, so the client has an id to quote even if it did not
  supply one.

### Slow-query log

[`backend/repositories/base.py:27-38`](../../backend/repositories/base.py:27):

```python
async def _execute(self, stmt, *, method: str = "unknown"):
    start = time.perf_counter()
    result = await self.session.execute(stmt)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms >= settings.SLOW_QUERY_THRESHOLD_MS:
        logger.warning(
            "Slow query detected",
            duration_ms=round(elapsed_ms, 2),
            table=self.model.__tablename__,
            method=method,
        )
    return result
```

- Threshold: `settings.SLOW_QUERY_THRESHOLD_MS`, default **500 ms**.
  Override via environment variable.
- The emitted record inherits `request_id` from the contextvar, so
  a slow-query warning is automatically grouped with the request
  that triggered it in the aggregator.
- **The slow-query wrapper only fires for calls that go through
  `_execute`.** `BaseRepository.get` / `get_multi` /
  `get_multi_paginated` and the soft-delete variants do. Ad-hoc
  `uow.session.execute(...)` calls made inside service `_pre_*`
  hooks (ADR-001 §5) do **not** — that is the trade-off we accepted
  for keeping "count dependent children" inline in a hook. If a
  service query becomes a hot path, promote it to a repository
  helper so it goes through `_execute`.

### Error-envelope correlation

The global `AppException` handler and the unhandled-exception
fallback (ADR-005) both fetch `request_id` from
`structlog.contextvars.get_contextvars()` and include it in the
`ErrorResponse` body:

```json
{
  "error_code": "SYSTEM_NOT_FOUND",
  "detail": "The requested system was not found.",
  "request_id": "b5d6f2a0-1234-4abc-9def-0123456789ab"
}
```

A user pasting that id into a support ticket gives the operator a
one-shot grep.

### Log-level guidance

- `logger.debug(...)` — entity CRUD retrievals (ADR-002's
  `get_by_id`, `get_paginated`). High cardinality; off in prod by
  default via `LOG_LEVEL=INFO`.
- `logger.info(...)` — lifecycle events (request started / finished,
  entity created / updated / deleted, superuser bootstrap).
- `logger.warning(...)` — slow queries, soft-delete restore,
  non-fatal anomalies.
- `logger.error(...)` — request failed (middleware), unhandled
  exception (global handler). Always with `exc_info` attached.

### What lives outside the logs

- **Auth tokens** (access JWT, refresh tokens). Never log them, never
  put them in contextvars. `logging_middleware` does not read
  `Authorization`.
- **Hashed passwords / password hashes.** Never log, never return.
  User DTOs do not expose them.
- **Secret paths, when the environment treats them as sensitive.**
  See ADR-013 §5 for the policy.
- **PII in request bodies.** The middleware logs method, path,
  status, and timing — not the body. If an individual endpoint
  needs body-level auditing, it adds its own bounded log line with
  only the domain-relevant fields; never `body.model_dump()`.

### Testing

- Unit tests for log output use `structlog.testing.capture_logs()`
  where assertions on emitted records matter.
- API tests assert on `X-Request-ID` echo and on the
  `error_code`/`request_id` fields of error envelopes.
- Slow-query logging is exercised by tuning
  `SLOW_QUERY_THRESHOLD_MS` very low in a targeted test and
  asserting the warning fires.

### Operating the aggregator (deployment concern)

- In production, set `LOG_RENDERER=json` and point the collector at
  stdout. One JSON document per line.
- Keep `LOG_LEVEL=INFO` unless debugging; `DEBUG` emits entity
  retrieval records per request that are noisy at scale.
- `REQUEST_ID_HEADER` can be renamed (e.g. to match an upstream
  edge proxy's header) without code changes.

### What we deliberately do not do

- **No per-endpoint timing histograms.** The middleware's
  `process_time` on `Request finished` is adequate for a
  post-hoc aggregator query. If latency dashboards become a hard
  requirement, add a Prometheus exporter (Option D) as a follow-up
  ADR.
- **No user-id injection into every log line by default.** The
  middleware binds `user_agent`, not `user_id` — extracting
  `user_id` would require parsing the JWT before the auth dependency
  runs, which inverts the layer order. Individual services that
  already have `creator_id` pass it explicitly to log records where
  it matters (see `GenericService.create`).
- **No distributed tracing.** Single-service deployment today; add
  trace propagation when a second service shares a request path
  with AIDE.
- **No sampling.** Every request is logged; at current volumes this
  is tractable and simpler than a sampling strategy.

## 6. Consequences

- **Easier:** support tickets arrive with a `request_id` that
  grep-points to the exact server-side story; slow queries surface
  without per-query instrumentation; dev logs are readable, prod
  logs are ingestible.
- **Harder:** deep latency analysis across layers is a log-query
  job, not a flame-graph click; ad-hoc service queries that bypass
  `_execute` are silent in the slow-query channel; the first time
  we fork an `asyncio.Task` off the request context we have to
  propagate contextvars manually.
- **Revisit when:** traffic or complexity justifies APM (Option C);
  the organisation adopts W3C Trace-Context at the edge (Option E);
  a consistent latency SLA demands per-endpoint histograms (Option
  D).
