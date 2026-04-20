# ADR-012: JWT Authentication with Refresh Token Rotation

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

Every non-public endpoint in the AIDE backend is gated by a FastAPI
dependency that resolves "the current user". The auth story has to
work for three client types with different characteristics:

- **Interactive admin UI** — browsers; session length measured in
  hours; operator expects rapid re-auth if a token is stolen.
- **SDK / crawler runs** — Python processes; session length measured
  in hours to days; they need to authenticate once and keep running
  without manual refresh.
- **Technical integrations** — long-running background services with
  their own credentials; sessions measured in weeks.

We need an auth model that:

1. Gives every protected endpoint a cheap, stateless check on every
   request — no DB round-trip per hit.
2. Provides a rotation mechanism so a stolen token has a bounded
   blast radius.
3. Supports explicit logout (per-token and per-user).
4. Lets the catalog privilege a small set of users (superuser) for
   destructive operations (delete, restore) without building a full
   RBAC model.
5. Aligns with OAuth2 client libraries so the SDK and third-party
   tools can use standard flows.

## 2. Options Considered

### Option A: JWT access token + opaque rotating refresh token + `is_superuser` flag — **chosen**

- **Access token** — JWT (HS256 by default, algorithm and secret read
  from settings), short-lived, carries `{user_id, exp}`. Validated on
  every request with no DB call.
- **Refresh token** — cryptographically random, 48-byte
  `secrets.token_urlsafe` string, stored in the DB only as a
  SHA-256 hash. The server gives the client the raw token once; the
  hash is what is looked up on refresh.
- **Rotation** — the refresh endpoint revokes the used refresh token
  and issues a new pair atomically inside one UoW.
- **Per-user-type lifetime** — `UserType.TECHNICAL` gets a longer
  refresh window (days to weeks) than `UserType.REGULAR`. Both are
  driven by settings.
- **Superuser gate** — `User.is_superuser` is a boolean column;
  `get_current_superuser` is the dependency that enforces it. There
  is no per-resource ACL, no roles, no permissions.
- **Password hashing** — `bcrypt` via `backend.core.security`.
- **Rate limits** — `5/minute` on `/login`, `10/minute` on `/refresh`,
  via `slowapi`.

| Dimension | Assessment |
|-----------|------------|
| Per-request overhead | **Minimal** — JWT verify + a `SELECT user WHERE id = ?` in the auth dependency |
| Revocation granularity | **Per refresh token** (fine) / **per user** (via `is_active` or revoke-all) |
| Blast radius of a leaked access token | **Bounded by expiry** (minutes) |
| Blast radius of a leaked refresh token | **One use** — any refresh revokes the token that initiated it |
| Authorization complexity | **Low** — a single boolean `is_superuser` |
| Compatibility with OAuth2 clients | **High** — uses the password-grant flow and bearer-token scheme |

**Pros:**

- Access tokens are stateless: the auth dependency can verify them
  with the signing key alone. The one DB hit in `get_current_user`
  loads the user record (to check `is_active`, `is_superuser`) —
  that is unavoidable for any model that honours server-side
  account status.
- Refresh tokens are opaque secrets stored only as hashes: a DB dump
  does not yield usable tokens. SHA-256 is adequate because the raw
  token is already 48 random bytes.
- Rotation bounds the damage window for a leaked refresh token —
  using it once revokes it, so the attacker and the user race, and
  the refresh endpoint's rate limit favours the server.
- `is_superuser` avoids the complexity of a full RBAC scheme for a
  product that currently has two actor classes: everyday users and
  administrators. Introducing roles later is compatible (add a
  `role` column; preserve `is_superuser` as a shortcut or deprecate
  it).
- `slowapi` rate limits make credential-stuffing and refresh-abuse
  noticeably harder.

**Cons:**

- Access tokens cannot be revoked before expiry (standard JWT
  limitation). Mitigated by short expiries and the
  `is_active`/`is_superuser` check on every request.
- Refresh-token rotation produces reconciliation problems for clients
  that accidentally double-submit the same refresh token — the
  second call fails with `REFRESH_TOKEN_REVOKED`. This is the
  desired behaviour, but clients must handle it.
- The secret key must be strong (settings enforce a minimum length —
  see ADR-016 when written). A weak key defeats the entire chain.

### Option B: Server-side sessions (opaque cookie backed by a `sessions` table)

Every request looks up the session id in the DB.

**Pros:** instant server-side revocation; rich session metadata;
familiar pattern.
**Cons:** a DB hit per request; cookie-based flows are awkward for
CLI and SDK clients; horizontal scale puts pressure on the
`sessions` table.

### Option C: JWT access token only (no refresh token)

Single JWT with a long expiry (hours to days).

**Pros:** simplest; one token type.
**Cons:** no way to revoke early; users re-login when the token
expires; no "remember me" semantics without exposing long-lived
credentials in storage.

### Option D: OAuth2 with an external identity provider (Auth0, Keycloak,
Okta)

Delegate authentication entirely.

**Pros:** SSO; MFA; enterprise integration; fewer crypto concerns for
the AIDE team.
**Cons:** adds an operational dependency; not justified at the
current scale; mapping external identities to `User` rows still
requires the same `is_superuser` flag we already have. Reasonable to
adopt later; not now.

### Option E: Full RBAC (roles + permissions tables)

Fine-grained authorization.

**Pros:** future-proof for complex permission models.
**Cons:** build cost is non-trivial; every new endpoint must
enumerate the permissions it requires; at the present scale the only
real distinction is "anyone vs. admin". Premature.

## 3. Trade-off Analysis

Option B pays a per-request DB cost that JWT avoids. Option C trades
control for simplicity in the wrong direction. Option D is a good
future target but brings an operational dependency we do not need
yet. Option E builds machinery for permissions that do not exist in
the product today.

Option A matches the product's current auth requirements (two actor
classes, three client types, explicit revocation) and leaves room to
evolve — `UserType` can grow, `is_superuser` can be replaced by a
`role` column, and the refresh-token table is ready to be joined
with a more sophisticated session-management table if one ever lands.

## 4. Recommendation

Adopt Option A. JWT access tokens for speed; rotating opaque refresh
tokens for revocability; `is_superuser` as the single authorization
axis until real RBAC is required.

## 5. Implementation Notes

### Tokens — where things live

| File | Role |
|------|------|
| [`backend/core/security.py`](../../backend/core/security.py) | `create_access_token`, `decode_access_token`, `generate_refresh_token`, `hash_refresh_token`, `verify_password`, `get_password_hash` — the crypto layer |
| [`backend/services/auth_service.py`](../../backend/services/auth_service.py) | `AuthService.authenticate_user`, `create_tokens_for_user`, `refresh_access_token`, `revoke_refresh_token`, `revoke_all_user_tokens` — the business layer |
| [`backend/models/refresh_token.py`](../../backend/models/refresh_token.py) | `RefreshToken` — `token_hash`, `user_id`, `expires_at`, `revoked_at`, `client_info` |
| [`backend/api/v1/login.py`](../../backend/api/v1/login.py) | `/api/v1/login`, `/api/v1/login/refresh`, `/api/v1/login/logout`, `/api/v1/login/logout-all` |
| [`backend/api/dependencies.py`](../../backend/api/dependencies.py) | `get_current_user`, `get_current_user_optional`, `get_current_superuser` — the dependency layer |
| [`backend/schemas/token.py`](../../backend/schemas/token.py) | `Token`, `TokenData`, `RefreshTokenRequest` — the wire format |

### Access-token shape

- JWT, algorithm `settings.JWT_ALGORITHM` (default `HS256`), signed
  with `settings.JWT_SECRET_KEY`.
- Claims: `{ "user_id": "<uuid-string>", "exp": <unix-ts> }`.
- Lifetime: `settings.ACCESS_TOKEN_EXPIRE_MINUTES` (default short —
  minutes, not hours).
- Opaque to the client beyond the `expires_in` hint returned in the
  token envelope.

The access token carries only the user id. Everything else — the
`is_active`, `is_superuser`, `email`, `full_name`, `user_type` —
comes from `uow.users.get(user_id)` in the auth dependency. This
lets an account be disabled, promoted, or demoted without waiting
for every outstanding access token to expire.

### Refresh-token shape

- Raw value: `secrets.token_urlsafe(48)` — 48 bytes of crypto-random
  data, URL-safe base64 encoded. Given to the client once.
- Stored: `sha256(raw).hexdigest()` in `refresh_tokens.token_hash`,
  unique and indexed. The raw token is never persisted or logged.
- Columns: `user_id` (FK `users.id` with `ondelete="CASCADE"`),
  `expires_at` (TZ-aware), `revoked_at` (nullable TZ-aware),
  `client_info` (User-Agent, nullable).
- Lifetime: `settings.REFRESH_TOKEN_EXPIRE_DAYS` for regular users,
  `settings.REFRESH_TOKEN_EXPIRE_DAYS_TECHNICAL` for
  `UserType.TECHNICAL`. The branch is inside
  `create_tokens_for_user`.

The `refresh_tokens` table uses `DateTime(timezone=True)` — unlike
the naive-UTC convention in the soft-delete / timestamp mixins
(ADR-006 §5). Refresh-token lifetimes cross server-process boundaries
more often than other domain data (a crawler on another host, a CLI
in another timezone), so TZ-aware storage is the deliberate choice
here and should stay.

### The auth flow

**Login** — `POST /api/v1/login/`

- Body: `application/x-www-form-urlencoded` (`OAuth2PasswordRequestForm`).
- Verifies the password via bcrypt; raises `AppException(INVALID_CREDENTIALS)`
  on miss (404-404 equivalence — "wrong email" and "wrong password"
  return the same code).
- Issues `{ access_token, refresh_token, token_type: "bearer",
  expires_in }`.
- Rate-limited at `5/minute` per client.

**Refresh** — `POST /api/v1/login/refresh`

- Body: `{ "refresh_token": "<raw>" }`.
- Hashes the incoming token, looks up the row, checks
  `revoked_at is None` and `expires_at > now`.
- Revokes the old token by setting `revoked_at = now()` in the same
  UoW transaction.
- Re-reads the user to re-check `is_active` (a disabled user loses
  access immediately on their next refresh).
- Issues a fresh pair via `create_tokens_for_user`.
- Rate-limited at `10/minute` per client.

**Logout** — `POST /api/v1/login/logout`

- Body: `{ "refresh_token": "<raw>" }`.
- Revokes the single token if it exists and is still active. Silent
  on unknown tokens — the endpoint does not confirm or deny token
  existence.
- Returns `204 NO_CONTENT`.

**Logout-all** — `POST /api/v1/login/logout-all`

- Requires a valid access token (`Depends(get_current_user)`).
- Revokes every refresh token for that user via
  `uow.refresh_tokens.revoke_all_for_user(user_id)`.

### Dependency layer

Three dependencies in
[`backend/api/dependencies.py`](../../backend/api/dependencies.py):

- `get_current_user` — required. Decodes the JWT via
  `decode_access_token`, loads the user, checks `is_active`,
  `expunge`s the ORM instance so it survives the `async with uow`
  block (ADR-003).
- `get_current_user_optional` — returns the user if a valid token is
  present, `None` otherwise. Used by endpoints that behave
  differently for authenticated vs. anonymous callers (for example
  `include_deleted=true` on list endpoints, gated on
  `is_superuser`).
- `get_current_superuser` — composes `get_current_user` and rejects
  non-superusers with HTTP 403.

The superuser dependency is what `create_crud_router` wires into the
delete/restore paths by default (see ADR-001 §5). Per-endpoint opt-
outs are explicit.

### Security rules

- Access tokens live only in memory or Authorization headers — do
  not log them. The JWT middleware does not log token payloads.
- Refresh tokens must be treated as bearer credentials: transmit
  over HTTPS, never in URL query strings.
- `JWT_SECRET_KEY` is validated at settings load time for a minimum
  length. Deployments must set it; the app refuses to start with a
  weak key.
- CORS for production forbids wildcard-origin + `Allow-Credentials`.
  This is enforced in the settings layer — see the settings
  validators in `backend/core/settings.py`.
- Never return the refresh-token hash, the user's
  `hashed_password`, or other internal columns from an API response
  — the DTOs enforce this, but reviewers should double-check new
  endpoints.

### Creating users programmatically

- The initial superuser is bootstrapped on startup from
  `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD` by
  [`_ensure_initial_superuser`](../../backend/main.py:41).
- All other users are created through `POST /api/v1/users` (gated on
  superuser).
- `UserType.TECHNICAL` marks a user whose sessions are expected to
  last longer (CI runners, service accounts); the type has no other
  effect on authorization.

### Testing

- Service tests (ADR-007) mock `uow.users` and `uow.refresh_tokens`
  and exercise `AuthService.authenticate_user`,
  `refresh_access_token`, and `revoke_*` branches.
- API tests exercise `/login`, `/refresh`, `/logout`, and
  `/logout-all` end-to-end with real bcrypt hashing and real JWT
  signing; see `tests/api/test_login.py`.
- Rate-limiter state is reset between tests by the autouse
  `_reset_rate_limits` fixture (ADR-007).

### What not to do

- Do not store the refresh token raw in the DB. Always hash.
- Do not encode authorization data (permissions, roles) into the JWT
  claims. The server decides authorization from the live `User` row
  on every request.
- Do not skip the `revoked_at` + `expires_at` check in `refresh_access_token`
  even if the lookup succeeds — an expired or revoked token that
  still matches the hash must be rejected.
- Do not mint an access token outside `create_access_token`. If a
  test needs a token, import and call the helper. Hand-rolled JWTs
  drift from the server's signing parameters.
- Do not extend the access-token lifetime to "solve" the SDK having
  to refresh. The SDK already refreshes automatically; the short
  access-token window is a feature.

## 6. Consequences

- **Easier:** most endpoints need nothing more than
  `Depends(get_current_user)`; superuser-only endpoints swap in
  `get_current_superuser`; the auth surface is four endpoints and
  one dependency module.
- **Harder:** debugging a stale access token requires the reviewer
  to understand the short expiry + refresh cycle; introducing finer
  authorization later is a code change, not a configuration one.
- **Revisit when:** the product gains more than two actor classes
  (add a `role` column; demote `is_superuser` to a derived property),
  or when an enterprise SSO / MFA story becomes a requirement
  (pivot toward Option D via OIDC).
