"""Service settings — environment variables only (MASTER_SPEC Part 9 §2).

Configuration is read from the process environment (prefix ``XTALATE_``) with an optional ``.env``
file for local development; ``.env.example`` is the committed, commented template. There is no
config file format and no code-baked default that a deployment cannot override — Part 9 §2 makes
the environment the single source, so that one artifact (the same image) behaves per its
environment in Tier 0, Tier 1, and a hosted instance without a rebuild.

The *limit* values below are surfaced by ``GET /v1/limits`` from M21, but their **enforcement**
lands with the surfaces that need them (upload size and rate limits in M24, the
``awaiting_recovery`` TTL in M23). Surfacing them first is deliberate: the client learns the rules
before it hits them (Part 6 §5). Default values are the *design-intent* numbers of Part 6 §5,
re-validated per-version rather than inherited silently (v0.5 standing rule 4) — they are not yet
a hosted-instance policy, which is v1.0 work.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All service configuration, populated from the environment (``XTALATE_`` prefix).

    Instances are immutable-by-convention and cached (:func:`get_settings`); a test constructs its
    own ``Settings(...)`` and passes it to :func:`~backend.app.create_app` to override without
    touching the process environment.
    """

    model_config = SettingsConfigDict(
        env_prefix="XTALATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- identity -------------------------------------------------------------------------------
    #: Free-form deployment label surfaced in logs and ``/v1/health`` (e.g. "development",
    #: "tier1", "production"). Never branches scientific behaviour — the library is environment-
    #: blind by construction.
    environment: str = "development"

    #: Base URL the error envelope's ``documentation_url`` is built from (Part 6 §6). Points at
    #: the published API error reference; the per-error anchor is the stable machine ``code``.
    docs_base_url: str = "https://github.com/jsong1218/Xtalate/blob/main/docs/API.md"

    # --- limits (surfaced by GET /v1/limits now; enforced in M23/M24) ---------------------------
    #: Largest upload accepted, in bytes (enforced during streaming in M24 → ``413``).
    max_upload_bytes: int = 100 * 1024 * 1024

    #: Hard cap on trajectory frames a single job will read; already enforced by the parser
    #: (``FRAME_LIMIT_EXCEEDED``), surfaced here so a client can size a request in advance.
    max_frames: int = 100_000

    #: Concurrent non-terminal jobs a single caller may hold (enforced in M24 → ``429``).
    max_concurrent_jobs: int = 4

    #: Sustained request rate per caller per minute (enforced in M24 → ``429`` + ``Retry-After``).
    rate_limit_per_minute: int = 120

    #: How long uploaded input bytes live before the storage lifecycle sweeps them (Part 9 §5.2).
    #: Reports outlive this window by construction (M24 reports-outlive-bytes).
    upload_retention_hours: int = 24

    #: How long converted output bytes remain downloadable before the same sweep removes them.
    output_retention_hours: int = 24

    #: TTL for a job paused in ``awaiting_recovery`` before it resolves to a **refusal** — never a
    #: silently applied default (Part 6 §3.2, enforced in M23). Capped by the input's own expiry.
    awaiting_recovery_ttl_minutes: int = 30

    #: Days a conversion record + its reports are retained (the longer of the two retention
    #: windows; Revision 1.5). ``None`` = indefinite, the self-hosted default posture.
    report_retention_days: int | None = 30

    # --- auth (v0.5 scope: anonymous self-hosted mode + optional static keys; Part 6 §4) ---------
    #: Optional static API key(s), comma-separated (``XTALATE_API_KEYS="k1,k2"``). **Empty = the
    #: anonymous self-hosted default**: no key required, history is instance-wide (Part 6 §4). When
    #: set, every ``/v1`` request (bar health) must carry ``Authorization: Bearer <key>`` with a
    #: listed key or it is ``401 UNAUTHORIZED``. Account machinery (signup/login, per-user keys) is
    #: hosted-instance work, deferred — ``/v1/auth/*`` and ``/v1/keys*`` are ``404 NOT_ENABLED``.
    #: Supplied via the environment only, never committed (CLAUDE.md "Never commit secrets").
    api_keys: str = ""

    @property
    def api_key_set(self) -> frozenset[str]:
        """The configured static API keys as a set (empty = anonymous mode). Comma-separated env."""
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

    # --- database (v0.5 M21 slice 3) ------------------------------------------------------------
    #: SQLAlchemy URL. SQLite (Tier 0, no services) is the default; Tier 1 sets a PostgreSQL URL
    #: (``postgresql+psycopg://…``). One interface, two backends — Part 9 §1.1.
    database_url: str = "sqlite+pysqlite:///./_xtalate.db"

    #: Echo SQL to logs (debugging only; never on in a deployment — logs must not carry content).
    database_echo: bool = False

    # --- job queue (v0.5 M21 slice 4; the worker + enqueue path arrive in M22) -------------------
    #: Redis URL the RQ queue connects to (``docs/private/DECISIONS.md`` D82). Read by the ``rq``
    #: queue backend and the worker (M22); ignored by the ``inline`` backend.
    redis_url: str = "redis://127.0.0.1:6379/0"

    #: Which job-queue backend to build (:func:`~backend.jobs.queue.create_job_queue`). ``"inline"``
    #: is the Tier 0 default: a submitted job runs synchronously in-process, so Tier 0 needs no
    #: Redis and no separate worker (a parser bug fix must never require Docker — Part 9 §1.1).
    #: ``"rq"`` targets Redis (Tier 1): the API enqueues, the ``backend.worker`` process executes.
    #: Two backends, one interface — the same pattern as object storage and the database (D82).
    queue_backend: str = "inline"

    #: RQ queue name and per-job timeout (seconds) for the ``rq`` backend. The timeout is the wall
    #: clock a single convert/inspect/validate may run before RQ marks it failed (Part 6 §3).
    queue_name: str = "xtalate"
    job_timeout_seconds: int = 1800

    # --- object storage (v0.5 M21 slice 2) ------------------------------------------------------
    #: Which object-storage backend to build (:func:`~backend.storage.create_object_store`).
    #: ``"filesystem"`` is the Tier 0 default (no services); ``"s3"`` targets S3-compatible storage
    #: (MinIO in Tier 1). Two backends, one interface — Part 9 §1.1.
    object_store_backend: str = "filesystem"

    #: Root directory for the filesystem backend (created on first use). Ignored for ``s3``.
    object_store_root: str = "./_xtalate_objects"

    #: Bucket the ``s3`` backend reads and writes. Private always (Part 9 §5.3).
    object_store_bucket: str = "xtalate"

    #: S3 endpoint URL for the ``s3`` backend (e.g. ``http://minio:9000``); ``None`` = AWS default.
    object_store_endpoint: str | None = None

    #: S3 region for the ``s3`` backend (MinIO ignores it but boto3 wants one set).
    object_store_region: str = "us-east-1"

    #: S3 credentials for the ``s3`` backend. Supplied via the environment only, never committed
    #: (CLAUDE.md "Never commit secrets"); ``None`` falls back to boto3's default credential chain.
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """The process-wide cached :class:`Settings` (read once from the environment).

    Cached so every request and dependency observes the same configuration snapshot. Tests that
    need a different configuration construct ``Settings(...)`` directly and pass it to
    :func:`~backend.app.create_app`, bypassing this cache.
    """
    return Settings()
