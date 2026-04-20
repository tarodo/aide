# ADR-013: Credential Indirection via `CredentialRef`

**Status:** Accepted
**Date:** 2026-04-20
**Deciders:** Backend team lead

---

## 1. Context and Problem

Every `System` AIDE catalogues is, eventually, a thing that a client
has to connect to — a PostgreSQL instance, a Kafka cluster, a Hive
metastore, an SFTP endpoint. The crawler (and, in the future, any
agent that queries a remote system on behalf of AIDE) needs
credentials to do its job: a database username and password, an API
token, a TLS key, an OAuth client secret.

The metastore has three kinds of data that can be confused with one
another:

1. **Descriptive metadata** — the system name, code, kind, flavor,
   layer, tags. Safe to store, safe to index, safe to show in every
   list view.
2. **Connection parameters** — host, port, database name, SASL
   protocol, Kafka topic. Not secret; operational.
3. **Secrets** — passwords, private keys, bearer tokens, anything
   whose compromise means a third-party system is compromised.

A metadata catalogue must never become the canonical store for class
(3). If it does, the blast radius of a DB leak or a compromised admin
account is every external system the catalogue knows about. The
compliance posture (GDPR, SOC 2, internal security reviews) also
hinges on not holding secrets the catalogue does not need.

We need a model that lets a `System` say *"my credentials live at
`vault://secret/data/aide/db-prod-ro`"* without AIDE ever seeing the
secret's value.

## 2. Options Considered

### Option A: `CredentialRef` indirection — **chosen**

- Introduce a dedicated `credential_refs` table containing only three
  domain columns: `provider` (the secret store's identifier),
  `path` (the location inside that store), and an optional `version`
  integer for stores that track secret versions.
- `System.credential_ref_id` is a nullable FK into this table — some
  systems genuinely need no credential; others share a credential
  across many systems.
- Secret resolution is the consumer's job. When the crawler (or any
  other agent) picks up a `System`, it reads the `CredentialRef`,
  asks the named provider for the value at the given path + version,
  and uses it in-memory. AIDE itself never stores, reads, or even
  sees the value.
- Access to the underlying secret store is authenticated separately
  — the crawler's deployment context carries the secret store's own
  auth (e.g. a Vault AppRole, a cloud IAM role). AIDE does not
  delegate any authority to its clients beyond "this system expects
  a credential at this reference".

| Dimension | Assessment |
|-----------|------------|
| Secrets in AIDE DB | **None** |
| Blast radius of a DB leak | **Low** — leaks reveal where secrets live, not what they are |
| Ability to rotate secrets | **High** — bump the version in the secret store; clients re-read |
| Sharing one secret across systems | **Native** — many-to-one via FK |
| Provider flexibility | **High** — `provider` is a free-form string |
| Audit of who read a secret | **At the secret store**, not at AIDE |

**Pros:**

- A complete DB dump of AIDE is uninteresting to an attacker — they
  learn the topology of secret references, not the secrets. The
  lateral-move path through AIDE is short.
- Secret rotation is decoupled from AIDE: rotate the underlying
  secret and bump the `CredentialRef.version`; every consumer picks
  up the new version on the next fetch. No metadata migration.
- One credential can back many systems (a shared service account
  across replicas of the same database) without duplicating the
  secret location; on the other side, different systems can
  explicitly share a `CredentialRef` so operational tooling can
  reason about "which systems would break if this credential is
  revoked?".
- Compliance conversations are short: "We do not store secrets in
  the catalogue."

**Cons:**

- The catalogue cannot verify on its own that a `CredentialRef`
  points to a live secret — validation requires reaching the
  provider, which AIDE does not do. A reference can dangle; the
  consumer discovers it at use time.
- `provider` is a free-form string: a typo in the value does not
  fail at `POST /credential-refs`. We accept the trade-off to stay
  provider-agnostic; the consumer knows its valid providers.
- Per-system secret resolution pushes responsibility to the clients.
  Every consumer has to implement (or depend on a library for) the
  secret-store adapters it needs.

### Option B: Store secrets directly (encrypted at rest)

Keep secrets inline on the `System` row, encrypted with a key that
lives in application configuration or a KMS.

**Pros:** one-stop shop; the catalogue is fully self-contained.
**Cons:** AIDE becomes a secrets vault and inherits all the
responsibilities — key rotation, envelope encryption, per-secret
audit log, key-escape containment. It also competes with the
organisation's real secrets manager and loses: no compliance team
will accept two canonical stores for the same secret.

### Option C: Fetch secrets into AIDE on write, cache, return on demand

AIDE reads the secret from the provider once at registration time,
stores it encrypted, and serves it to clients.

**Pros:** clients do not need provider adapters.
**Cons:** rotation loops through AIDE; the cached copy drifts; the
catalogue holds secrets again, inheriting every problem of Option B
plus the new problem of stale secrets.

### Option D: No `CredentialRef` table — put `provider` and `path`
directly on `System`

Skip the indirection entirely.

**Pros:** one fewer table.
**Cons:** cannot share a credential reference across systems without
duplicating the `(provider, path)` pair; cannot soft-delete a
reference independently of its systems; cannot enforce uniqueness of
a `(provider, path)` pair at the catalogue level.

### Option E: A full-blown secret broker service

Stand up a separate service that fronts the secret store, issues
short-lived tokens to consumers, and logs every access.

**Pros:** auditable; lifecycle control.
**Cons:** massively over-scoped for a metadata catalogue; the
organisation likely already has such a broker (Vault, AWS Secrets
Manager, a cloud KMS) — duplicating that is wasted effort.

## 3. Trade-off Analysis

The central axis is **what AIDE is for**. It is a catalogue, not a
secrets manager. Options B, C, and E pull AIDE into the secrets-
management business, which amplifies its blast radius and competes
with the organisation's real secret store. Option D removes the
table but also removes the affordances (sharing, lifecycle,
uniqueness, auditable list of references). Option A keeps AIDE in
its own lane: it knows *where* a secret lives; it does not know
*what* the secret is.

## 4. Recommendation

Adopt Option A. Store only the reference tuple
`(provider, path, version?)`; let consumers fetch the actual secret
from the provider they name.

## 5. Implementation Notes

### Data model

[`backend/models/credential_ref.py`](../../backend/models/credential_ref.py):

```python
class CredentialRef(Base, SoftDeleteMetaDataMixin):
    __tablename__ = "credential_refs"
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    path:     Mapped[str] = mapped_column(Text,        nullable=False)
    version:  Mapped[int | None] = mapped_column(Integer, nullable=True)

    systems = relationship("System", back_populates="credential_ref")

    __table_args__ = (
        Index(
            "uq_credential_refs_provider_path_active",
            "provider", "path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
```

- **`provider`** is a string — intentionally free-form so the
  catalogue does not need a code change to support a new secret
  store. Canonical values today are chosen by the consumer (e.g.
  `vault`, `aws-secrets-manager`, `k8s-secret`, `env`).
- **`path`** is the opaque location inside that provider
  (`secret/data/aide/db-prod-ro`, `prod/aide/snowflake`, a JSON path,
  a Kubernetes namespace/name combo).
- **`version`** is optional; populate it for stores that return
  versioned secrets and you need to pin to a specific version.
  Leaving it `NULL` means "the latest version the provider returns".
- The unique index prevents registering the same `(provider, path)`
  twice while active; soft-delete + partial index allows re-creation
  later (ADR-006).
- There is **no column for the secret value**. No `ciphertext`, no
  `hash`, no `encrypted_blob`. Adding one is a proposal to reverse
  this ADR and must be argued on its own merits.

[`backend/models/system.py`](../../backend/models/system.py):

```python
credential_ref_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("credential_refs.id"), nullable=True,
)
credential_ref = relationship("CredentialRef", back_populates="systems")
```

- Nullable — some systems are credentialed by the network boundary
  alone (e.g. intra-VPC HTTP) and do not need a reference.
- No `ondelete` clause — default `RESTRICT` plus soft-delete logic
  in the service (see below) gives us the right behaviour without
  a cascade.

### Service contract

[`backend/services/credential_ref.py`](../../backend/services/credential_ref.py)
is a straightforward `SoftDeleteService` (ADR-002 / ADR-006) with
three hooks:

- `_pre_create`: rejects a duplicate `(provider, path)` among active
  rows with `AppException(CREDENTIAL_REF_ALREADY_EXISTS)`.
- `_pre_update`: re-checks uniqueness when either field changes.
- `_pre_delete`: counts active `System`s that reference this ref and
  raises `AppException(HAS_DEPENDENT_ENTITIES)` if any. This keeps
  an operator from orphaning systems through an unintentional
  delete.

[`backend/services/system.py`](../../backend/services/system.py) on
create/update of a `System` verifies that a referenced
`credential_ref_id` exists (`CREDENTIAL_REF_NOT_FOUND` otherwise) —
the `CredentialRef` must be pre-registered before being attached to
a system.

### Consumer contract

A client that needs the actual secret value follows three steps:

1. `GET /api/v1/systems/{id}` → read `credential_ref_id`.
2. `GET /api/v1/credential-refs/{id}` → read `provider`, `path`,
   `version`.
3. Call the provider. Example (Vault): `vault kv get -version=<v>
   <path>`. Example (AWS): `aws secretsmanager get-secret-value
   --secret-id <path> --version-id <v-id>`.

The consumer is responsible for:

- Mapping `provider` strings to its own adapter for that store.
- Authenticating with the provider using its own credentials
  (AppRole, IAM role, kubelet identity). **AIDE does not mediate
  this.**
- Caching the fetched secret **in-memory only** and respecting the
  provider's TTL / rotation policy.
- Never writing the fetched secret back to AIDE or to any log sink.

### Adding a new provider

There is no code change in the backend. Clients may agree on a new
`provider` string (for example `k8s-secret`) and start using it; the
catalogue accepts any value. If a provider becomes prevalent enough
to warrant server-side validation or a provider-specific
`params_schema` (analogous to data types — ADR-011), that will be a
follow-up ADR that tightens the current free-form string.

### API surface

`/api/v1/credential-refs` follows the standard CRUD router shape
(ADR-001 §5): list with filters, get by id, create, update, soft-
delete, restore. The superuser gate (ADR-012) applies to delete and
restore by default.

`list` and `get_by_id` responses include `provider`, `path`, and
`version`. These are not secrets; they are safe to return and to log.
If the organisation treats secret *paths* as sensitive (some
Vault deployments do), the deployment's audit configuration should
scrub them at the log collector — AIDE does not gate them.

### What the crawler does today

[`crawler/`](../../crawler) is the canonical consumer. It:

1. Reads a target `System` via the SDK.
2. Resolves the `CredentialRef` to a live secret using its own
   adapter code (outside this repo's secrets scope).
3. Opens a connection to the described system using that secret.
4. Writes metadata observations back to AIDE using its own API
   credentials, which are *different* from the credentials it
   fetched from the provider.

The separation keeps "AIDE API auth" (ADR-012) orthogonal to
"connected-system auth" (this ADR). A compromise of either does not
imply the other.

### What not to do

- Do not add a `secret_value`, `encrypted_secret`, or similar column.
  This is the single most important invariant of this ADR.
- Do not log `provider` / `path` in structured logs if your
  environment considers them sensitive; audit rules live with the
  consumer, not with AIDE.
- Do not let the backend dial out to a secret store "to validate
  that the path exists at registration time". The backend is not a
  client of the secret store; that is the consumer's role. Adding
  an optional round-trip would pull AIDE into the secrets-fetching
  path (Option C in reverse).
- Do not delete a `CredentialRef` out from under a `System`. The
  `_pre_delete` check enforces this; do not bypass it with direct
  SQL in production.
- Do not reuse a `CredentialRef` row as a "slot" — if the secret's
  location changes (new path, new provider), update the fields
  through the API so the `row_version` trail exists; do not repoint
  the row in place through `UPDATE credential_refs SET provider=...`.

### Testing

- Service unit tests (ADR-007) verify: duplicate detection, the
  uniqueness re-check on update, the dependent-`System` count on
  delete, and the standard soft-delete + restore path.
- API tests cover the round-trip through `/api/v1/credential-refs`.
- Because no adapter code lives in the backend, there is nothing to
  mock for secret resolution — tests end at the FK boundary.

## 6. Consequences

- **Easier:** a compromise of AIDE does not compromise the connected
  systems; rotation is a provider-side operation; compliance review
  of the catalogue is short.
- **Harder:** consumers must each speak to the secret store; a
  dangling `CredentialRef` (wrong `path`, wrong `version`) surfaces
  as an error at use time, not at registration; organisations without
  a real secrets manager cannot adopt AIDE fully until they stand
  one up.
- **Revisit when:** the organisation converges on a single canonical
  secret store and we want to tighten `provider` from a free-form
  string to a registered enum; or when a common need emerges for
  AIDE to verify references at write time (at which point the
  backend would acquire its own read-only, scoped identity in the
  secret store — a deliberate scope expansion that must come with
  its own ADR).
