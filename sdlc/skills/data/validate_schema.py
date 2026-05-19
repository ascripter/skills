"""Validate DATA-MODEL.yaml against the canonical sdlc-data schema, and run
cross-checks against the upstream PRD.yaml (feature coverage) plus internal
consistency checks (relationship integrity, classification integrity,
bounded-context partition, volume-vs-scale gate).

Run from the project root:

    python sdlc/skills/data/validate_schema.py
    python sdlc/skills/data/validate_schema.py --path docs/DATA-MODEL.yaml

Validates:
    1. docs/DATA-MODEL.yaml (or --path) — single-file data model.
    2. Cross-checks (7 total; hardness as marked):
       - Required fields present: REQUIRED_PATHS + ENTITY_REQUIRED_PATHS.
         Failure -> hard error in status:complete.
       - Relationship integrity: every from_entity / to_entity / join_table
         exists in `entities`. Failure -> hard error in status:complete.
       - Field references: every entities.<E>.fields.<f>.references value
         resolves to a real Entity.field. Failure -> hard error.
       - Classification integrity: every Entity.field in pii_fields /
         regulated_fields / encrypted_at_rest resolves. Failure -> hard error.
       - Bounded-context partition: when bounded_contexts present, every
         entity belongs to exactly one context. Failure -> hard error.
       - Mode-mismatch: monorepo: true requires products:; false forbids it.
         Failure -> hard error (raised by the pydantic model_validator).
       - Feature coverage: every PRD must_have_features F-NNN appears in some
         entity's traces_prd_features. Failure -> force draft (soft).
       - Volume-vs-scale gate: if PRD data_volume_estimate in {terabytes,
         petabytes}, scale_and_retention must be non-null. Failure -> force
         draft (soft).

Exit codes:
    0 — schema valid; either status='complete' (with all required fields filled
        AND all enabled checks passing) or status='draft'.
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing, OR status='complete' but any cross-check failed.
    2 — could not read or parse the file (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

try:
    import yaml
except ImportError:
    print(
        "ERROR: pyyaml is required.\nInstall with:  pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(3)

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
except ImportError:
    print(
        "ERROR: pydantic v2 is required.\nInstall with:  pip install 'pydantic>=2'",
        file=sys.stderr,
    )
    sys.exit(3)


# =============================================================================
# Enums — kept in lockstep with DATA-MODEL.schema.yaml
# =============================================================================


class Confidence(str, Enum):
    confirmed = "confirmed"
    inferred = "inferred"
    assumption = "assumption"


class PrimaryStore(str, Enum):
    postgres = "postgres"
    mysql = "mysql"
    sqlite = "sqlite"
    mongodb = "mongodb"
    dynamodb = "dynamodb"
    sqlserver = "sqlserver"
    oracle = "oracle"
    other = "other"


class SecondaryStoreKind(str, Enum):
    redis = "redis"
    memcached = "memcached"
    elasticsearch = "elasticsearch"
    opensearch = "opensearch"
    meilisearch = "meilisearch"
    kafka = "kafka"
    rabbitmq = "rabbitmq"
    clickhouse = "clickhouse"
    duckdb = "duckdb"
    other = "other"


class SecondaryStoreRole(str, Enum):
    cache = "cache"
    search = "search"
    queue = "queue"
    analytics = "analytics"
    timeseries = "timeseries"
    other = "other"


class FileBlobStore(str, Enum):
    none = "none"
    s3 = "s3"
    gcs = "gcs"
    azure_blob = "azure_blob"
    minio = "minio"
    local_fs = "local_fs"
    other = "other"


class IdScheme(str, Enum):
    uuid_v4 = "uuid_v4"
    uuid_v7 = "uuid_v7"
    ulid = "ulid"
    nanoid = "nanoid"
    serial_int = "serial_int"
    bigserial = "bigserial"
    natural_key = "natural_key"
    mixed = "mixed"


class FieldType(str, Enum):
    uuid = "uuid"
    string = "string"
    text = "text"
    int_ = "int"
    bigint = "bigint"
    decimal = "decimal"
    float_ = "float"
    bool_ = "bool"
    date = "date"
    time = "time"
    timestamp = "timestamp"
    timestamptz = "timestamptz"
    json_ = "json"
    jsonb = "jsonb"
    enum = "enum"
    binary = "binary"
    blob = "blob"
    array = "array"
    other = "other"

    @classmethod
    def _missing_(cls, value: object):
        # Tolerate Python-keyword clashes (int/float/bool/json) by re-mapping
        # the value strings back to the enum members.
        mapping = {
            "int": cls.int_,
            "float": cls.float_,
            "bool": cls.bool_,
            "json": cls.json_,
        }
        if isinstance(value, str) and value in mapping:
            return mapping[value]
        return None


class Cardinality(str, Enum):
    one_one = "1:1"
    one_many = "1:N"
    many_many = "N:M"


class OnDelete(str, Enum):
    cascade = "cascade"
    restrict = "restrict"
    set_null = "set_null"
    no_action = "no_action"


class PartitioningStrategy(str, Enum):
    range = "range"
    list_ = "list"
    hash = "hash"
    none = "none"

    @classmethod
    def _missing_(cls, value: object):
        if value == "list":
            return cls.list_
        return None


class RecordVersioning(str, Enum):
    none = "none"
    row_version = "row_version"
    temporal_table = "temporal_table"
    event_sourcing = "event_sourcing"


class IsolationLevel(str, Enum):
    read_committed = "read_committed"
    repeatable_read = "repeatable_read"
    serializable = "serializable"
    snapshot = "snapshot"


class CachingLayer(str, Enum):
    none = "none"
    in_process = "in_process"
    redis = "redis"
    memcached = "memcached"
    other = "other"


class FulltextEngine(str, Enum):
    none = "none"
    postgres_fts = "postgres_fts"
    elasticsearch = "elasticsearch"
    opensearch = "opensearch"
    meilisearch = "meilisearch"
    typesense = "typesense"


class AnalyticsTarget(str, Enum):
    none = "none"
    bigquery = "bigquery"
    snowflake = "snowflake"
    redshift = "redshift"
    duckdb = "duckdb"
    other = "other"


class CdcStrategy(str, Enum):
    none = "none"
    debezium = "debezium"
    outbox = "outbox"
    trigger = "trigger"
    other = "other"


class MigrationTool(str, Enum):
    alembic = "alembic"
    flyway = "flyway"
    liquibase = "liquibase"
    prisma_migrate = "prisma_migrate"
    drizzle_kit = "drizzle_kit"
    sqlx = "sqlx"
    knex = "knex"
    django_migrate = "django_migrate"
    activerecord = "activerecord"
    other = "other"


class IndexType(str, Enum):
    btree = "btree"
    hash = "hash"
    gin = "gin"
    gist = "gist"
    fulltext = "fulltext"
    composite = "composite"
    other = "other"


class SyncModel(str, Enum):
    pull = "pull"
    push = "push"
    webhook = "webhook"
    stream = "stream"


class RetentionPolicy(str, Enum):
    hard_delete = "hard_delete"
    archive = "archive"
    anonymize = "anonymize"


# =============================================================================
# Models — keep nested theme models permissive (extra="allow") so the file can
# carry forward-compat keys without breaking validation; reject enum values strictly.
# =============================================================================


_BASE_CONFIG = ConfigDict(extra="allow", str_strip_whitespace=True)


class _Permissive(BaseModel):
    model_config = _BASE_CONFIG


class FieldSpec(_Permissive):
    type: Optional[FieldType] = None
    nullable: Optional[bool] = None
    primary_key: Optional[bool] = None
    unique: Optional[bool] = None
    default: Optional[Any] = None
    references: Optional[str] = None       # "Entity.field"
    on_delete: Optional[OnDelete] = None
    check: Optional[str] = None
    comment: Optional[str] = None


class Entity(_Permissive):
    description: Optional[str] = None
    primary_key: Optional[Union[str, List[str]]] = None
    fields: Optional[Dict[str, FieldSpec]] = None
    traces_prd_features: Optional[List[str]] = None
    traces_ux_surfaces: Optional[List[str]] = None


class SecondaryStore(_Permissive):
    kind: Optional[SecondaryStoreKind] = None
    role: Optional[SecondaryStoreRole] = None
    rationale: Optional[str] = None


class Persistence(_Permissive):
    primary_store: Optional[PrimaryStore] = None
    primary_store_confidence: Optional[Confidence] = None
    primary_store_rationale: Optional[str] = None
    polyglot: Optional[bool] = None
    secondary_stores: Optional[List[SecondaryStore]] = None
    secondary_stores_confidence: Optional[Confidence] = None
    file_blob_store: Optional[FileBlobStore] = None
    file_blob_store_bucket: Optional[str] = None
    file_blob_store_rationale: Optional[str] = None


class NaturalKey(_Permissive):
    entity: Optional[str] = None
    fields: Optional[List[str]] = None
    reason: Optional[str] = None


class IdStrategy(_Permissive):
    scheme: Optional[IdScheme] = None
    scheme_confidence: Optional[Confidence] = None
    scheme_rationale: Optional[str] = None
    natural_keys: Optional[List[NaturalKey]] = None


class Relationship(_Permissive):
    from_entity: Optional[str] = None
    from_field: Optional[str] = None
    to_entity: Optional[str] = None
    to_field: Optional[str] = None
    cardinality: Optional[Cardinality] = None
    on_delete: Optional[OnDelete] = None
    on_update: Optional[OnDelete] = None
    join_table: Optional[str] = None
    comment: Optional[str] = None


class EnumsAndLookups(_Permissive):
    enums: Optional[Dict[str, List[str]]] = None
    lookup_tables: Optional[List[str]] = None


class AccessPattern(_Permissive):
    description: Optional[str] = None
    entity: Optional[str] = None
    fields: Optional[List[str]] = None
    expected_qps: Optional[float] = None
    latency_budget_ms: Optional[int] = None
    read_or_write: Optional[Literal["read", "write", "both"]] = None


class IndexSpec(_Permissive):
    entity: Optional[str] = None
    fields: Optional[List[str]] = None
    unique: Optional[bool] = None
    type: Optional[IndexType] = None
    name: Optional[str] = None


class IndexesAndQueries(_Permissive):
    access_patterns: Optional[List[AccessPattern]] = None
    expected_indexes: Optional[List[IndexSpec]] = None


class UniqueConstraint(_Permissive):
    entity: Optional[str] = None
    fields: Optional[List[str]] = None
    name: Optional[str] = None


class CheckConstraint(_Permissive):
    entity: Optional[str] = None
    expression: Optional[str] = None
    name: Optional[str] = None
    comment: Optional[str] = None


class IntegrityAndConstraints(_Permissive):
    default_on_delete: Optional[OnDelete] = None
    default_on_delete_rationale: Optional[str] = None
    unique_constraints: Optional[List[UniqueConstraint]] = None
    check_constraints: Optional[List[CheckConstraint]] = None


class DataClassification(_Permissive):
    pii_fields: Optional[List[str]] = None
    pii_fields_confidence: Optional[Confidence] = None
    regulated_fields: Optional[List[str]] = None
    regulated_fields_confidence: Optional[Confidence] = None
    encrypted_at_rest: Optional[List[str]] = None
    encryption_kms_ref: Optional[str] = None
    retention_policy_default: Optional[str] = None


class BoundedContext(_Permissive):
    description: Optional[str] = None
    entities: Optional[List[str]] = None


class AuditColumns(_Permissive):
    created_at: Optional[bool] = None
    updated_at: Optional[bool] = None
    created_by: Optional[bool] = None
    updated_by: Optional[bool] = None
    deleted_at: Optional[bool] = None


class AuditAndLifecycle(_Permissive):
    audit_columns: Optional[AuditColumns] = None
    soft_delete: Optional[bool] = None
    soft_delete_rationale: Optional[str] = None
    archive_strategy: Optional[str] = None
    applies_to: Optional[List[str]] = None


class VersioningAndHistory(_Permissive):
    record_versioning: Optional[RecordVersioning] = None
    record_versioning_rationale: Optional[str] = None
    history_retention: Optional[str] = None
    applies_to: Optional[List[str]] = None


class RetentionPolicyItem(_Permissive):
    entity: Optional[str] = None
    ttl: Optional[str] = None
    policy: Optional[RetentionPolicy] = None


class ScaleAndRetention(_Permissive):
    partitioning_key: Optional[str] = None
    partitioning_strategy: Optional[PartitioningStrategy] = None
    sharding_key: Optional[str] = None
    retention_policies: Optional[List[RetentionPolicyItem]] = None


class MigrationsAndEvolution(_Permissive):
    tool: Optional[MigrationTool] = None
    tool_confidence: Optional[Confidence] = None
    zero_downtime_strategy: Optional[str] = None
    rollback_policy: Optional[str] = None


class TransactionsAndConsistency(_Permissive):
    default_isolation: Optional[IsolationLevel] = None
    default_isolation_rationale: Optional[str] = None
    transaction_boundaries: Optional[List[str]] = None


class CachedEntity(_Permissive):
    entity: Optional[str] = None
    ttl: Optional[str] = None
    invalidation: Optional[str] = None


class CachingLayerBlock(_Permissive):
    layer: Optional[CachingLayer] = None
    layer_confidence: Optional[Confidence] = None
    cached_entities: Optional[List[CachedEntity]] = None


class IndexedEntity(_Permissive):
    entity: Optional[str] = None
    fields: Optional[List[str]] = None


class SearchAndAnalytics(_Permissive):
    fulltext_engine: Optional[FulltextEngine] = None
    fulltext_engine_confidence: Optional[Confidence] = None
    fulltext_engine_rationale: Optional[str] = None
    indexed_entities: Optional[List[IndexedEntity]] = None
    analytics_target: Optional[AnalyticsTarget] = None
    cdc_strategy: Optional[CdcStrategy] = None


class SeedAndFixtures(_Permissive):
    seed_strategy: Optional[str] = None
    dev_fixtures_path: Optional[str] = None


class ExternalDataSource(_Permissive):
    name: Optional[str] = None
    sync_model: Optional[SyncModel] = None
    conflict_resolution: Optional[str] = None
    refresh_interval: Optional[str] = None
    maps_to_entity: Optional[str] = None


# -----------------------------------------------------------------------------
# Top-level
# -----------------------------------------------------------------------------


class Metadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_model_version: str
    last_updated: str
    generated_by: str = "sdlc-data"
    session_id: str
    monorepo: bool = False
    status: Literal["draft", "complete"] = "draft"


class DataModelProduct(_Permissive):
    """One product's data model in monorepo mode."""

    persistence: Optional[Persistence] = None
    id_strategy: Optional[IdStrategy] = None
    entities: Optional[Dict[str, Entity]] = None
    relationships: Optional[List[Relationship]] = None
    enums_and_lookups: Optional[EnumsAndLookups] = None
    indexes_and_queries: Optional[IndexesAndQueries] = None
    integrity_and_constraints: Optional[IntegrityAndConstraints] = None
    data_classification: Optional[DataClassification] = None
    bounded_contexts: Optional[Dict[str, BoundedContext]] = None
    audit_and_lifecycle: Optional[AuditAndLifecycle] = None
    versioning_and_history: Optional[VersioningAndHistory] = None
    scale_and_retention: Optional[ScaleAndRetention] = None
    migrations_and_evolution: Optional[MigrationsAndEvolution] = None
    transactions_and_consistency: Optional[TransactionsAndConsistency] = None
    caching_layer: Optional[CachingLayerBlock] = None
    search_and_analytics: Optional[SearchAndAnalytics] = None
    seed_and_fixtures: Optional[SeedAndFixtures] = None
    external_data_sources: Optional[List[ExternalDataSource]] = None


class DataModel(BaseModel):
    """Top-level docs/DATA-MODEL.yaml document."""

    model_config = ConfigDict(extra="allow")

    metadata: Metadata
    data_warnings: List[str] = Field(default_factory=list)

    # Single-product theme blocks (in interview order)
    persistence: Optional[Persistence] = None
    id_strategy: Optional[IdStrategy] = None
    entities: Optional[Dict[str, Entity]] = None
    relationships: Optional[List[Relationship]] = None
    enums_and_lookups: Optional[EnumsAndLookups] = None
    indexes_and_queries: Optional[IndexesAndQueries] = None
    integrity_and_constraints: Optional[IntegrityAndConstraints] = None
    data_classification: Optional[DataClassification] = None
    bounded_contexts: Optional[Dict[str, BoundedContext]] = None
    audit_and_lifecycle: Optional[AuditAndLifecycle] = None
    versioning_and_history: Optional[VersioningAndHistory] = None
    scale_and_retention: Optional[ScaleAndRetention] = None
    migrations_and_evolution: Optional[MigrationsAndEvolution] = None
    transactions_and_consistency: Optional[TransactionsAndConsistency] = None
    caching_layer: Optional[CachingLayerBlock] = None
    search_and_analytics: Optional[SearchAndAnalytics] = None
    seed_and_fixtures: Optional[SeedAndFixtures] = None
    external_data_sources: Optional[List[ExternalDataSource]] = None

    # Multi-product mode
    products: Optional[Dict[str, DataModelProduct]] = None

    @model_validator(mode="after")
    def _check_mode(self) -> "DataModel":
        single_themes = [
            self.persistence,
            self.id_strategy,
            self.entities,
            self.relationships,
            self.enums_and_lookups,
            self.indexes_and_queries,
            self.integrity_and_constraints,
            self.data_classification,
            self.bounded_contexts,
            self.audit_and_lifecycle,
            self.versioning_and_history,
            self.scale_and_retention,
            self.migrations_and_evolution,
            self.transactions_and_consistency,
            self.caching_layer,
            self.search_and_analytics,
            self.seed_and_fixtures,
            self.external_data_sources,
        ]
        any_single = any(t is not None for t in single_themes)

        if self.metadata.monorepo:
            if not self.products:
                raise ValueError(
                    "metadata.monorepo is true but `products` is missing or empty"
                )
            if any_single:
                raise ValueError(
                    "monorepo mode set but top-level theme blocks are present; "
                    "in monorepo mode every theme must live under `products.<slug>`"
                )
        else:
            if self.products:
                raise ValueError(
                    "`products` is set but metadata.monorepo is false; "
                    "either set monorepo: true or move themes to top level"
                )
        return self


# =============================================================================
# Required-field check — only enforced when metadata.status == "complete"
# =============================================================================

# Paths required at top level (or under each product in monorepo mode).
REQUIRED_PATHS: List[str] = [
    "persistence.primary_store",
    "id_strategy.scheme",
    "entities",
    "relationships",
    "indexes_and_queries.access_patterns",
    "integrity_and_constraints.default_on_delete",
    "data_classification.pii_fields",
]

# Per-entity required fields (checked inside each entry of `entities`).
ENTITY_REQUIRED_PATHS: List[str] = [
    "description",
    "fields",
    "primary_key",
    "traces_prd_features",
]

# Paths where the key must be PRESENT (not None) but an empty list is allowed.
# Matches the top-level pattern for `relationships`, `pii_fields`, and
# `access_patterns`: the user has to explicitly answer the question, but
# "I don't trace any F-NNN feature" is a valid answer for purely-backend
# entities like AuditLog. The feature-coverage cross-check enforces global
# completeness across all entities.
ENTITY_PRESENT_ONLY_PATHS: set = {"traces_prd_features"}


def _get_dotted(obj: object, path: str) -> object:
    cur: object = obj
    for part in path.split("."):
        if cur is None:
            return None
        # Models use attribute access; dicts use key access.
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        # entities {} is empty — required; relationships [] is allowed (key present
        # but no edges). We handle this differentiation in the caller.
        return True
    return False


def check_required(dm: DataModel) -> List[str]:
    """Return a flat list of missing required field paths.

    `entities` must be a non-empty dict. `relationships` only requires the key
    to be present (empty list is allowed — no edges is a valid model).
    `data_classification.pii_fields` only requires the key present too — an
    empty list is the user saying "no PII fields", which is a valid answer.
    """
    missing: List[str] = []

    def _check(scope_label: str, root: object) -> None:
        for path in REQUIRED_PATHS:
            val = _get_dotted(root, path)
            if path == "entities":
                # Must be a non-empty dict.
                if not isinstance(val, dict) or len(val) == 0:
                    missing.append(f"{scope_label}{path}")
                continue
            if path in ("relationships", "data_classification.pii_fields",
                        "indexes_and_queries.access_patterns"):
                # Key must be present (not None); empty list is OK.
                # An explicit "no edges / no PII / no listed patterns" answer
                # is valid — the agent has thought about it and recorded it.
                # The feature-coverage cross-check is the real "did you think
                # about scope" guard.
                if val is None:
                    missing.append(f"{scope_label}{path}")
                continue
            if _is_empty(val):
                missing.append(f"{scope_label}{path}")

        # Per-entity required fields.
        entities = _get_dotted(root, "entities")
        if isinstance(entities, dict):
            for ename, entity in entities.items():
                for ep in ENTITY_REQUIRED_PATHS:
                    val = _get_dotted(entity, ep)
                    if ep == "fields":
                        if not isinstance(val, dict) or len(val) == 0:
                            missing.append(f"{scope_label}entities.{ename}.{ep}")
                    elif ep in ENTITY_PRESENT_ONLY_PATHS:
                        if val is None:
                            missing.append(f"{scope_label}entities.{ename}.{ep}")
                    elif _is_empty(val):
                        missing.append(f"{scope_label}entities.{ename}.{ep}")

    if dm.metadata.monorepo and dm.products:
        for slug, product in dm.products.items():
            _check(f"products.{slug}.", product)
    else:
        _check("", dm)
    return missing


# =============================================================================
# Cross-checks
# =============================================================================

_FEATURE_ID_RE = re.compile(r"^F-\d+", re.IGNORECASE)


def _entity_names(root: object) -> List[str]:
    entities = _get_dotted(root, "entities")
    if isinstance(entities, dict):
        return list(entities.keys())
    return []


def _entity_field_names(root: object, entity_name: str) -> List[str]:
    entity = (_get_dotted(root, "entities") or {}).get(entity_name)
    if entity is None:
        return []
    fields = getattr(entity, "fields", None)
    if isinstance(fields, dict):
        return list(fields.keys())
    return []


def check_relationship_integrity(root: object) -> List[str]:
    """Every relationship's from_entity, to_entity, and (for N:M) join_table
    must exist as a key in `entities`. Field names referenced must exist on
    the corresponding entity."""
    errs: List[str] = []
    rels = _get_dotted(root, "relationships")
    if not isinstance(rels, list):
        return errs
    enames = set(_entity_names(root))
    for i, rel in enumerate(rels):
        # rel is a Relationship model
        fe = getattr(rel, "from_entity", None)
        te = getattr(rel, "to_entity", None)
        ff = getattr(rel, "from_field", None)
        tf = getattr(rel, "to_field", None)
        card = getattr(rel, "cardinality", None)
        jt = getattr(rel, "join_table", None)

        if fe and fe not in enames:
            errs.append(f"relationships[{i}].from_entity: '{fe}' not in entities")
        if te and te not in enames:
            errs.append(f"relationships[{i}].to_entity: '{te}' not in entities")
        if fe in enames and ff and ff not in _entity_field_names(root, fe):
            errs.append(
                f"relationships[{i}].from_field: '{ff}' not a field on '{fe}'"
            )
        if te in enames and tf and tf not in _entity_field_names(root, te):
            errs.append(
                f"relationships[{i}].to_field: '{tf}' not a field on '{te}'"
            )
        if card == Cardinality.many_many:
            if not jt:
                errs.append(
                    f"relationships[{i}].join_table: required when cardinality == 'N:M'"
                )
            elif jt not in enames:
                errs.append(
                    f"relationships[{i}].join_table: '{jt}' not in entities"
                )
    return errs


def check_field_references(root: object) -> List[str]:
    """Every entity field with a `references: Entity.field` must resolve."""
    errs: List[str] = []
    entities = _get_dotted(root, "entities")
    if not isinstance(entities, dict):
        return errs
    enames = set(entities.keys())
    for ename, entity in entities.items():
        fields = getattr(entity, "fields", None) or {}
        if not isinstance(fields, dict):
            continue
        for fname, field in fields.items():
            ref = getattr(field, "references", None)
            if not ref:
                continue
            if "." not in ref:
                errs.append(
                    f"entities.{ename}.fields.{fname}.references: '{ref}' "
                    f"must be 'Entity.field' format"
                )
                continue
            ref_entity, _, ref_field = ref.partition(".")
            if ref_entity not in enames:
                errs.append(
                    f"entities.{ename}.fields.{fname}.references: "
                    f"'{ref_entity}' not in entities"
                )
                continue
            if ref_field not in _entity_field_names(root, ref_entity):
                errs.append(
                    f"entities.{ename}.fields.{fname}.references: "
                    f"'{ref_field}' not a field on '{ref_entity}'"
                )
    return errs


def check_classification_integrity(root: object) -> List[str]:
    """Every Entity.field listed in pii_fields, regulated_fields, encrypted_at_rest
    must resolve to a real field on a real entity."""
    errs: List[str] = []
    dc = _get_dotted(root, "data_classification")
    if dc is None:
        return errs
    entities = _get_dotted(root, "entities") or {}
    if not isinstance(entities, dict):
        return errs

    for list_name in ("pii_fields", "regulated_fields", "encrypted_at_rest"):
        items = getattr(dc, list_name, None) or []
        for i, ref in enumerate(items):
            if not isinstance(ref, str):
                errs.append(
                    f"data_classification.{list_name}[{i}]: must be a string "
                    f"in 'Entity.field' format, got {type(ref).__name__}"
                )
                continue
            if "." not in ref:
                errs.append(
                    f"data_classification.{list_name}[{i}]: '{ref}' "
                    f"must be 'Entity.field' format"
                )
                continue
            ent, _, fld = ref.partition(".")
            if ent not in entities:
                errs.append(
                    f"data_classification.{list_name}[{i}]: entity "
                    f"'{ent}' not found"
                )
                continue
            if fld not in _entity_field_names(root, ent):
                errs.append(
                    f"data_classification.{list_name}[{i}]: field "
                    f"'{fld}' not on entity '{ent}'"
                )
    return errs


def check_bounded_context_partition(root: object) -> List[str]:
    """When bounded_contexts is present, every entity in `entities` must be
    assigned to exactly one context (no orphans, no duplicates)."""
    errs: List[str] = []
    bcs = _get_dotted(root, "bounded_contexts")
    if not isinstance(bcs, dict) or len(bcs) == 0:
        return errs
    enames = set(_entity_names(root))

    assignments: Dict[str, List[str]] = {e: [] for e in enames}
    for ctx_name, ctx in bcs.items():
        ctx_ents = getattr(ctx, "entities", None) or []
        for ent in ctx_ents:
            if ent not in enames:
                errs.append(
                    f"bounded_contexts.{ctx_name}.entities: '{ent}' not in entities"
                )
                continue
            assignments[ent].append(ctx_name)

    for ent, ctxs in assignments.items():
        if len(ctxs) == 0:
            errs.append(
                f"bounded_contexts: entity '{ent}' is not assigned to any context"
            )
        elif len(ctxs) > 1:
            errs.append(
                f"bounded_contexts: entity '{ent}' is assigned to multiple "
                f"contexts: {ctxs}"
            )
    return errs


def load_prd_must_have_features(
    prd_path: Path,
) -> Dict[Optional[str], List[str]]:
    """Return PRD must_have_features F-NNN IDs, scoped correctly.

    Single-product mode: returns ``{None: [F-001, ...]}``.
    Monorepo mode: returns ``{"<slug>": [F-001, ...], ...}`` — one entry per
    product. Each product's features stay scoped to that product so the
    feature-coverage cross-check can compare each product's entities against
    only that product's features (rather than the union across all products,
    which would force every product to trace every other product's features).
    """
    if not prd_path.exists():
        return {None: []}
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {None: []}
    if not isinstance(raw, dict):
        return {None: []}

    monorepo = bool((raw.get("metadata") or {}).get("monorepo"))

    def _pull(node: dict) -> List[str]:
        out: List[str] = []
        fr = node.get("functional_requirements") or {}
        mhf = fr.get("must_have_features") if isinstance(fr, dict) else None
        if isinstance(mhf, list):
            for item in mhf:
                s = str(item).strip()
                m = _FEATURE_ID_RE.match(s)
                if m:
                    out.append(m.group(0).upper())
        return out

    if monorepo:
        result: Dict[Optional[str], List[str]] = {}
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for slug, prod in products.items():
                if isinstance(prod, dict):
                    result[slug] = _pull(prod)
        return result
    return {None: _pull(raw)}


def load_prd_data_volume(prd_path: Path) -> Optional[str]:
    """Return PRD.data_model.data_volume_estimate (or first product's), or None."""
    if not prd_path.exists():
        return None
    try:
        raw = yaml.safe_load(prd_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None

    monorepo = bool((raw.get("metadata") or {}).get("monorepo"))

    def _pull(node: dict) -> Optional[str]:
        dm = node.get("data_model") or {}
        if isinstance(dm, dict):
            v = dm.get("data_volume_estimate")
            if isinstance(v, str):
                return v
        return None

    if monorepo:
        for prod in (raw.get("products") or {}).values():
            if isinstance(prod, dict):
                v = _pull(prod)
                if v:
                    return v
    else:
        return _pull(raw)
    return None


def collect_traced_features(root: object) -> List[str]:
    """Aggregate traces_prd_features across all entities."""
    feats: List[str] = []
    entities = _get_dotted(root, "entities") or {}
    if not isinstance(entities, dict):
        return feats
    for entity in entities.values():
        tf = getattr(entity, "traces_prd_features", None)
        if isinstance(tf, list):
            for f in tf:
                m = _FEATURE_ID_RE.match(str(f).strip())
                if m:
                    feats.append(m.group(0).upper())
    return feats


def check_feature_coverage(prd_features: List[str], traced: List[str]) -> List[str]:
    """Return list of PRD F-NNN IDs that no entity traces."""
    traced_set = {f.upper() for f in traced}
    return [f for f in prd_features if f.upper() not in traced_set]


def check_volume_scale_gate(volume: Optional[str], root: object) -> Optional[str]:
    """If PRD volume ∈ {terabytes, petabytes}, scale_and_retention must be present
    and non-null. Returns an error string, or None."""
    if volume not in ("terabytes", "petabytes"):
        return None
    sar = _get_dotted(root, "scale_and_retention")
    if sar is None:
        return (
            f"scale_and_retention is required when PRD.data_volume_estimate "
            f"== '{volume}' but is absent"
        )
    # Must have at least one substantive field set.
    has_any = any(
        getattr(sar, name, None) is not None
        for name in (
            "partitioning_key", "partitioning_strategy", "sharding_key",
            "retention_policies",
        )
    )
    if not has_any:
        return (
            f"scale_and_retention is present but empty; PRD.data_volume_estimate "
            f"== '{volume}' requires at least one of partitioning_key, "
            f"partitioning_strategy, sharding_key, or retention_policies"
        )
    return None


# =============================================================================
# Driver
# =============================================================================


def _format_pydantic_errors(err: ValidationError) -> List[str]:
    formatted: List[str] = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()))
        msg = e.get("msg", "invalid")
        formatted.append(f"{loc}: {msg}")
    return formatted


def validate_file(path: Path) -> int:
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"ERROR: YAML parse error in {path}:\n  {e}", file=sys.stderr)
        return 2

    if raw is None:
        print(f"ERROR: {path} is empty", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print(
            f"ERROR: {path} top level must be a mapping, got {type(raw).__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        dm = DataModel.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] DATA-MODEL.yaml FAILED schema validation ({path})\n")
        print("Errors:")
        for line in _format_pydantic_errors(e):
            print(f"  - {line}")
        return 1

    # Per-product or single-product cross-checks.
    docs_dir = path.parent
    prd_path = docs_dir / "PRD.yaml"
    prd_features_by_scope = load_prd_must_have_features(prd_path)
    prd_volume = load_prd_data_volume(prd_path)

    relationship_errs: List[str] = []
    field_ref_errs: List[str] = []
    classification_errs: List[str] = []
    bounded_ctx_errs: List[str] = []
    uncovered_features: List[str] = []
    volume_errs: List[str] = []

    def _per_scope(scope_label: str, root: object, scope_features: List[str]) -> None:
        scope = scope_label if scope_label else ""
        for e_ in check_relationship_integrity(root):
            relationship_errs.append(f"{scope}{e_}")
        for e_ in check_field_references(root):
            field_ref_errs.append(f"{scope}{e_}")
        for e_ in check_classification_integrity(root):
            classification_errs.append(f"{scope}{e_}")
        for e_ in check_bounded_context_partition(root):
            bounded_ctx_errs.append(f"{scope}{e_}")
        volume_err = check_volume_scale_gate(prd_volume, root)
        if volume_err:
            volume_errs.append(f"{scope}{volume_err}")

        traced = collect_traced_features(root)
        for f in check_feature_coverage(scope_features, traced):
            uncovered_features.append(f"{scope}{f}")

    if dm.metadata.monorepo and dm.products:
        for slug, product in dm.products.items():
            scope_features = prd_features_by_scope.get(slug, [])
            _per_scope(f"products.{slug}.", product, scope_features)
    else:
        single_features = prd_features_by_scope.get(None, [])
        _per_scope("", dm, single_features)

    missing = check_required(dm)
    status = dm.metadata.status

    # Hard errors (block status:complete): missing required, relationship integrity,
    # field references, classification integrity, bounded-context partition,
    # mode mismatch (already caught by pydantic model_validator).
    # Soft errors (force draft): feature coverage gaps, volume-vs-scale gate.

    hard_problems = bool(
        missing or relationship_errs or field_ref_errs
        or classification_errs or bounded_ctx_errs
    )
    soft_problems = bool(uncovered_features or volume_errs)

    if status == "complete":
        if hard_problems or soft_problems:
            print(f"[FAIL] DATA-MODEL.yaml claims status 'complete' but has errors ({path})\n")
            if missing:
                print(f"{len(missing)} required field(s) missing:")
                for m in missing:
                    print(f"  - {m}")
                print()
            if relationship_errs:
                print(f"{len(relationship_errs)} relationship integrity error(s):")
                for e_ in relationship_errs:
                    print(f"  - {e_}")
                print()
            if field_ref_errs:
                print(f"{len(field_ref_errs)} field reference error(s):")
                for e_ in field_ref_errs:
                    print(f"  - {e_}")
                print()
            if classification_errs:
                print(f"{len(classification_errs)} classification integrity error(s):")
                for e_ in classification_errs:
                    print(f"  - {e_}")
                print()
            if bounded_ctx_errs:
                print(f"{len(bounded_ctx_errs)} bounded-context partition error(s):")
                for e_ in bounded_ctx_errs:
                    print(f"  - {e_}")
                print()
            if uncovered_features:
                print(
                    f"{len(uncovered_features)} PRD F-NNN feature(s) with no entity trace "
                    f"(feature-coverage check):"
                )
                for f in uncovered_features:
                    print(f"  - {f}")
                print()
            if volume_errs:
                print(f"{len(volume_errs)} volume-vs-scale gate error(s):")
                for e_ in volume_errs:
                    print(f"  - {e_}")
            return 1

        n_entities = sum(
            (len(p.entities or {}) for p in (dm.products or {}).values())
            if (dm.metadata.monorepo and dm.products) else [len(dm.entities or {})]
        )
        total_features = sum(len(v) for v in prd_features_by_scope.values())
        print(
            f"[OK] DATA-MODEL.yaml is valid and complete ({path}); "
            f"{n_entities} entit(y/ies); "
            f"{total_features} PRD F-NNN feature(s) all covered."
        )
        return 0

    # status == "draft"
    n_entities_msg = (
        sum(len(p.entities or {}) for p in (dm.products or {}).values())
        if (dm.metadata.monorepo and dm.products)
        else len(dm.entities or {})
    )
    total_features = sum(len(v) for v in prd_features_by_scope.values())
    print(
        f"[DRAFT] DATA-MODEL.yaml is a draft ({path}); "
        f"{n_entities_msg} entit(y/ies) defined; "
        f"{total_features} PRD F-NNN feature(s) discovered upstream."
    )
    if missing:
        print(f"\n{len(missing)} required field(s) missing:")
        for m in missing:
            print(f"  - {m}")
    if relationship_errs:
        print(f"\n{len(relationship_errs)} relationship integrity error(s):")
        for e_ in relationship_errs:
            print(f"  - {e_}")
    if field_ref_errs:
        print(f"\n{len(field_ref_errs)} field reference error(s):")
        for e_ in field_ref_errs:
            print(f"  - {e_}")
    if classification_errs:
        print(f"\n{len(classification_errs)} classification integrity error(s):")
        for e_ in classification_errs:
            print(f"  - {e_}")
    if bounded_ctx_errs:
        print(f"\n{len(bounded_ctx_errs)} bounded-context partition error(s):")
        for e_ in bounded_ctx_errs:
            print(f"  - {e_}")
    if uncovered_features:
        print(f"\n{len(uncovered_features)} PRD F-NNN feature(s) with no entity trace:")
        for f in uncovered_features:
            print(f"  - {f}")
    if volume_errs:
        print(f"\n{len(volume_errs)} volume-vs-scale gate error(s):")
        for e_ in volume_errs:
            print(f"  - {e_}")
    if not (missing or relationship_errs or field_ref_errs or classification_errs
            or bounded_ctx_errs or uncovered_features or volume_errs):
        print("\nAll required fields filled, all cross-checks pass. "
              "Set metadata.status: complete when done.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate DATA-MODEL.yaml against the sdlc-data schema."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("docs", "DATA-MODEL.yaml"),
        help="Path to DATA-MODEL.yaml (default: ./docs/DATA-MODEL.yaml).",
    )
    args = parser.parse_args(argv)
    return validate_file(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
