# ADR-005: Error Handling — Code Registry + `AppException` Handler

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

AIDE exposes a REST API consumed by the SDK, the crawler, and human
clients. Error responses need three properties:

1. **Machine-readable** — clients must branch on a stable identifier, not
   on the wording of a message. `USER_ALREADY_EXISTS` is stable;
   `"A user with this email already exists."` is not.
2. **Consistently shaped** — every error response carries the same
   envelope (`error_code`, `detail`, optional `request_id`) regardless of
   which layer raised it.
3. **Discoverable in OpenAPI** — for each endpoint, the documented
   response set should list exactly the error codes it can produce, with
   examples, so SDK codegen and API consumers know what to expect.

The logic that decides *when* to fail lives in the service layer (ADR-001,
ADR-002): `_pre_create` rejects duplicate codes, `_pre_delete` rejects
deletions of parents with children, `update` detects version conflicts.
The logic that decides *how* that failure renders as an HTTP response —
status code, detail text, envelope shape — belongs at the HTTP boundary.
The question is how to connect the two without coupling the service layer
to FastAPI primitives or duplicating detail strings across every router.

## 2. Options Considered

### Option A: Flat error-code registry + `AppException(code)` + global handler — **chosen**

- `backend/core/errors.py` defines a flat set of string constants (one
  per error) and an `ERROR_MAP` from code → `(http_status, detail)`.
- `backend/core/exceptions.py` defines a single `AppException(Exception)`
  that carries only the `error_code` string.
- Services raise `AppException(CODE)`; they never import FastAPI.
- A single `@app.exception_handler(AppException)` in `main.py` looks the
  code up in `ERROR_MAP` and renders the standard `ErrorResponse`
  envelope with the request id attached from structlog contextvars.
- A helper `build_error_responses(*codes)` turns a set of codes into a
  FastAPI `responses=` mapping with grouped examples for OpenAPI.

| Dimension | Assessment |
|-----------|------------|
| Service-layer coupling to HTTP | **None** — services only know strings |
| Consistency of envelope | **High** — one handler, one schema |
| OpenAPI accuracy | **High** — codes are declared per endpoint |
| Cost of adding an error | **Low** — one constant + one `ERROR_MAP` entry |
| Runtime overhead | **None** — O(1) dict lookup in the handler |

**Pros:**

- The service layer has no knowledge of HTTP status codes or detail
  text. A service can be unit-tested (ADR-007) with a mocked UoW and
  no FastAPI in scope.
- Adding a new error is a two-line diff in one file; every router that
  declares the code picks it up automatically in OpenAPI.
- The envelope is defined once (`ErrorResponse` in
  [`backend/schemas/error.py`](../../backend/schemas/error.py)) and
  carries the `request_id` from the structured-logging context, which
  gives operators a single handle to trace any reported error.
- `build_error_responses` enforces registry membership — passing an
  unregistered code raises `KeyError` at import time, so a drifted
  router does not silently document a non-existent error.

**Cons:**

- The set of error codes is global and flat; with enough entities it is
  a long file (currently ~50 codes).
- Each error's metadata (status, detail) is decoupled from the site
  that raises it — a reader chasing `raise AppException(SYSTEM_NOT_FOUND)`
  must consult `ERROR_MAP` to learn the status code.
- Changing the detail string is a global change: every client sees the
  new wording at the same time.

### Option B: Exception class hierarchy per error

A tree of `Exception` subclasses: `NotFoundError`, `SystemNotFoundError`,
`ConflictError`, `VersionConflictError`, etc. Each class carries its
status code and detail as class attributes. The handler dispatches by
`isinstance`.

**Pros:** carriers of rich context (each exception can take constructor
args); IDE discovery is nice ("find subclasses of `NotFoundError`").
**Cons:** an explosion of classes for what is structurally a map; every
new error is a new file or a new class; shared metadata (status, detail)
is duplicated across closely related exceptions; the service layer
imports exception classes that live under `backend.core`, which is still
fine — but the cardinality scales worse than a registry.

### Option C: Raise `HTTPException` directly in services

Services raise `fastapi.HTTPException(status_code=404, detail="…")` at
the point of failure; FastAPI handles the rest.

**Pros:** no custom registry; zero indirection.
**Cons:** services must know HTTP semantics, which breaks the layering
(ADR-001); detail strings are duplicated per raise site; there is no
machine-readable `error_code` for clients to branch on; swapping to a
gRPC or message-bus transport later would require replacing every raise
site.

### Option D: Outcome / Result return types (no exceptions for business errors)

Services return `Result[Ok, Err]` and the router pattern-matches on
failures.

**Pros:** explicit in the signature; no control-flow via exceptions.
**Cons:** Python's type system is not ergonomic for sum types; every
service call site grows a branch; nested validation hooks (`_pre_create`
inside `create`) lose the "fail fast" shape we already have; the change
is invasive for marginal benefit.

## 3. Trade-off Analysis

The core tension is **centralization vs. locality**: Option A
centralizes the code→status→detail mapping (one file to audit), at the
cost of forcing readers to cross-reference the registry from the raise
site. Option B spreads the same information across many classes, which
improves locality but inflates the class count. Options C and D conflate
layer concerns with transport mechanics.

For an evolving API with ~50 error conditions, dense code review around
a single registry file is cheaper than reviewing 50 exception subclasses.
The registry also makes it trivial to audit: "which codes return 401?"
is a single grep.

## 4. Recommendation

Adopt Option A. Services raise `AppException(CODE)`; the router layer
declares the codes it may produce via `build_error_responses`; the
global handler renders them.

## 5. Implementation Notes

### Registering a new error code

1. Add a constant to [`backend/core/errors.py`](../../backend/core/errors.py)
   in the constants block. Name it
   `UPPER_SNAKE_CASE`, scope-prefixed by entity or domain
   (`SYSTEM_NOT_FOUND`, `VERSION_CONFLICT`, `REFRESH_TOKEN_EXPIRED`). The
   value is the same literal string as the constant name — the constant
   exists for autocomplete; the string is what goes on the wire.
2. Add an entry to `ERROR_MAP` with the appropriate HTTP status and
   the user-facing detail text. Canonical statuses in use today:
   - `400 BAD_REQUEST` — invalid input that passed schema validation
     (uniqueness conflicts, cross-field constraints).
   - `401 UNAUTHORIZED` — bad or expired credentials.
   - `403 FORBIDDEN` — authenticated but not permitted.
   - `404 NOT_FOUND` — missing entity.
   - `409 CONFLICT` — state-level conflicts
     (`HAS_DEPENDENT_ENTITIES`, `VERSION_CONFLICT`).
   - `422 UNPROCESSABLE_ENTITY` — semantically invalid payloads beyond
     Pydantic validation (e.g. type-instance params failing a JSON
     schema check).
3. Import the constant where it is raised:
   ```python
   from backend.core import errors
   raise AppException(errors.SYSTEM_NOT_FOUND)
   ```

### Raising from the service layer

- Raise `AppException(CODE)` from validation hooks (`_pre_create`,
  `_pre_update`, `_pre_delete`) and from service methods themselves.
- The `_not_found_error_code` injected into each service's
  `GenericService.__init__` (see ADR-002) is the code raised when a
  lookup misses — do not re-implement the miss check in each hook.
- Never raise `HTTPException` from a service file. Never raise a bare
  `Exception` for a known business failure; use a registered code.

### Router declarations

Each endpoint declares the error codes it may produce via
`build_error_responses` (directly or through `create_crud_router`):

```python
crud_router = create_crud_router(
    ...,
    create_error_codes=[SYSTEM_ALREADY_EXISTS, SYSTEM_FLAVOR_NOT_FOUND],
    update_error_codes=[SYSTEM_NOT_FOUND, VERSION_CONFLICT, ...],
    get_one_error_codes=[SYSTEM_NOT_FOUND],
    delete_error_codes=[SYSTEM_NOT_FOUND, HAS_DEPENDENT_ENTITIES],
)
```

`build_error_responses` validates that every code is in `ERROR_MAP` and
groups codes with the same HTTP status into one `responses=` entry with
example bodies for each code. Passing an unregistered code raises
`KeyError` at startup — do not silently document a code that does not
exist.

### The global handler

[`backend/main.py`](../../backend/main.py) installs two handlers:

```python
@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    status_code, detail = ERROR_MAP.get(
        exc.error_code,
        (500, "An internal error occurred"),
    )
    ctx = structlog.contextvars.get_contextvars()
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error_code=exc.error_code,
            detail=detail,
            request_id=ctx.get("request_id"),
        ).model_dump(),
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception(...)
    return JSONResponse(500, ErrorResponse(
        error_code="INTERNAL_SERVER_ERROR",
        detail="An unexpected internal error occurred.",
        request_id=ctx.get("request_id"),
    ).model_dump())
```

The second handler guarantees that every response body is an
`ErrorResponse` envelope — even for bugs — so clients can always parse
failures with the same schema.

### The response envelope

[`backend/schemas/error.py`](../../backend/schemas/error.py):

```python
class ErrorResponse(BaseModel):
    error_code: str
    detail: str
    request_id: str | None = None
```

- `error_code` is what clients branch on; it matches the constant name.
- `detail` is human-readable and may be shown in UIs; do not parse it
  programmatically.
- `request_id` comes from the `logging_middleware` in `main.py` via
  structlog contextvars — the same id appears in server logs, so a
  client can report it and operators can grep.

### Using error codes where `HTTPException` is unavoidable

`HTTPException` remains appropriate for two narrow cases in the router
layer:

- `include_deleted=true` in a list endpoint where the caller is not a
  superuser — the check lives in `crud_router` before the service is
  called; this is a permission gate, not a business error.
- OAuth2 credential parsing failures in `get_current_user` — FastAPI's
  `HTTPBearer` conventions expect `HTTPException` for the 401 path.

In both cases the failure is purely HTTP-layer; the service would never
see it. Do not extend this carve-out to business rules.

### Do not do

- Do not branch on `detail` strings in tests or SDK code — assert on the
  `error_code`.
- Do not invent a new code ad hoc inside a service file without adding
  it to the registry; `build_error_responses` will reject it at startup
  only if a router declares it, so a stray code can linger undetected
  until a router catches up.
- Do not reuse a code for semantically different failures. Each code
  should have one precise meaning; ambiguity defeats the whole point of
  the registry.

## 6. Consequences

- **Easier:** clients branch on stable machine-readable codes; operators
  correlate logs with client-reported `request_id`s; adding a new error
  is localized.
- **Harder:** reading a `raise AppException(CODE)` site requires looking
  up the registry for the resulting HTTP status; maintaining the
  registry imposes review discipline as it grows.
- **Revisit when:** the registry grows past comfortable single-file
  size (split by domain — `errors/system.py`, `errors/dataset.py`,
  `errors/auth.py` — re-exported from `errors/__init__.py`), or when we
  introduce a second transport (gRPC, message bus) that needs its own
  code-to-error mapping.
