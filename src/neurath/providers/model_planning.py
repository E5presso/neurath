"""Durable, owner-scoped model plans; adapter observations are trusted inputs.

This module validates constraints and bindings, not model quality. Callers must
supply native owner identity and adapter-read inventory, never agent assertions of
availability. An unresolved default permits preparation of the same authorized
session only when no hard constraint would be violated by that preparation;
it does not authorize substantive work or a separate discovery session.
"""

import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 32768 or '\0' in value:
        raise ValueError('expected nonempty bounded text')


def _texts(values):
    if not isinstance(values, tuple) or len(values) > 128 or len(set(values)) != len(values):
        raise ValueError('expected distinct tuple values')
    for value in values:
        _text(value)


def _number(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise ValueError('expected finite nonnegative number')


def _json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > 1048576:
        raise ValueError('model plan exceeds bounded storage size')
    return encoded


@dataclass(frozen=True)
class Constraints:
    explicit_model: str | None = None
    allowed_providers: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    min_context_tokens: int | None = None
    max_input_price_per_million: float | None = None
    max_latency_ms: float | None = None

    def __post_init__(self):
        if self.explicit_model is not None:
            _text(self.explicit_model)
        _texts(self.allowed_providers)
        _texts(self.required_capabilities)
        for value in (self.min_context_tokens, self.max_input_price_per_million, self.max_latency_ms):
            _number(value)
        if self.min_context_tokens is not None and type(self.min_context_tokens) is not int:
            raise ValueError('context must be an integer')


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    capabilities: tuple[str, ...] = ()
    reasoning: tuple[str, ...] = ()
    context_tokens: int | None = None
    input_price_per_million: float | None = None
    latency_ms: float | None = None

    def __post_init__(self):
        _text(self.model_id)
        _texts(self.capabilities)
        _texts(self.reasoning)
        for value in (self.context_tokens, self.input_price_per_million, self.latency_ms):
            _number(value)


@dataclass(frozen=True)
class Inventory:
    provider: str
    host: str
    source: str
    revision: str
    models: tuple[ModelInfo, ...] = ()
    default_model: str | None = None
    default_source: str | None = None
    default_revision: str | None = None
    available: bool = True
    observed_at: float = 0

    def __post_init__(self):
        for value in (self.provider, self.host, self.source, self.revision):
            _text(value)
        if not isinstance(self.models, tuple) or len(self.models) > 1024 or any(not isinstance(m, ModelInfo) for m in self.models):
            raise ValueError('expected typed model observations')
        if len({m.model_id for m in self.models}) != len(self.models):
            raise ValueError('duplicate model observations')
        for value in (self.default_model, self.default_source, self.default_revision):
            if value is not None:
                _text(value)
        if type(self.available) is not bool:
            raise ValueError('availability must be boolean')
        _number(self.observed_at)


@dataclass(frozen=True)
class Selection:
    model: str = 'inherit'
    reasoning: str | None = None

    def __post_init__(self):
        _text(self.model)
        if self.reasoning is not None:
            _text(self.reasoning)


@dataclass(frozen=True)
class PlanContext:
    assignment_digest: str
    assignment_revision: int
    provider: str
    host: str
    policy_digest: str
    policy_mapping_revision: str
    constraints: Constraints = field(default_factory=Constraints)

    def __post_init__(self):
        for value in (self.assignment_digest, self.provider, self.host, self.policy_digest,
                      self.policy_mapping_revision):
            _text(value)
        if self.provider not in ('codex', 'claude-code'):
            raise ValueError('unsupported provider')
        if type(self.assignment_revision) is not int or self.assignment_revision < 1:
            raise ValueError('invalid assignment revision')
        if not isinstance(self.constraints, Constraints):
            raise TypeError('expected typed constraints')


@dataclass(frozen=True)
class PlanProposal:
    context: PlanContext
    selection: Selection
    difficulty: str
    evidence: tuple[str, ...]
    confidence: str
    rationale: str
    rejected_alternatives: tuple[str, ...]
    replan_triggers: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.context, PlanContext) or not isinstance(self.selection, Selection):
            raise TypeError('expected typed context and selection')
        if self.difficulty not in ('routine', 'standard', 'complex') or self.confidence not in ('low', 'medium', 'high'):
            raise ValueError('invalid difficulty or confidence')
        for values in (self.evidence, self.rejected_alternatives, self.replan_triggers):
            _texts(values)
        if not self.evidence or not self.replan_triggers:
            raise ValueError('evidence and replan triggers are required')
        _text(self.rationale)


def _selection(context, selection, inventory):
    if (context.provider, context.host) != (inventory.provider, inventory.host):
        raise ValueError('inventory target mismatch')
    constraints = context.constraints
    if constraints.allowed_providers and context.provider not in constraints.allowed_providers:
        raise ValueError('provider constraint mismatch')
    inherited = selection.model == 'inherit'
    resolved = inventory.default_model if inherited else selection.model
    if inherited and resolved and not (inventory.default_source and inventory.default_revision):
        raise ValueError('inherited default lacks observation provenance')
    if constraints.explicit_model and constraints.explicit_model != resolved:
        raise ValueError('explicit model constraint mismatch')
    if not resolved:
        if constraints != Constraints(allowed_providers=constraints.allowed_providers) or selection.reasoning is not None:
            raise ValueError('unresolved default cannot establish hard constraints')
        return {'status': 'preparation-only', 'resolved_model_id': None}
    info = next((m for m in inventory.models if m.model_id == resolved), None)
    if info is None or (not inventory.available and not inherited):
        raise ValueError('model unavailable or unverified')
    if selection.reasoning is not None and selection.reasoning not in info.reasoning:
        raise ValueError('unsupported reasoning setting')
    if not set(constraints.required_capabilities).issubset(info.capabilities):
        raise ValueError('required capabilities unverified')
    for label, limit, actual, minimum in (
        ('context', constraints.min_context_tokens, info.context_tokens, True),
        ('price', constraints.max_input_price_per_million, info.input_price_per_million, False),
        ('latency', constraints.max_latency_ms, info.latency_ms, False),
    ):
        if limit is not None and (actual is None or (actual < limit if minimum else actual > limit)):
            raise ValueError(f'{label} constraint unverified or exceeded')
    return {'status': 'ready', 'resolved_model_id': resolved}


class ModelPlanStore:
    def __init__(self, database_path=None, *, database=None):
        if (database_path is None) == (database is None):
            raise ValueError("provide exactly one model plan database")
        self.database = database
        self.path = (
            Path(database_path).absolute() if database is None else database.path
        )
        if database is None:
            self._safe_path()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.close(os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600))
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS model_plans (
                owner TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                request_key TEXT NOT NULL, proposal TEXT NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(owner,id,revision), UNIQUE(owner,request_key))''')

    def _safe_path(self):
        paths = [self.path, *self.path.parents, *(Path(str(self.path) + s) for s in ('-journal', '-wal', '-shm'))]
        if any(path.is_symlink() for path in paths):
            raise ValueError('model plan database paths must not be symlinks')

    @contextmanager
    def _db(self):
        if self.database is not None:
            with self.database.connection() as db:
                yield db
            return
        self._safe_path()
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    @staticmethod
    def _read(db, owner, plan_id, revision):
        row = db.execute('SELECT record FROM model_plans WHERE owner=? AND id=? AND revision=?',
                         (owner, plan_id, revision)).fetchone()
        if row is None:
            raise ValueError('plan missing or wrong owner')
        return json.loads(row['record'])

    def read(self, owner, plan_id, revision):
        with self._db() as db:
            return self._read(db, owner, plan_id, revision)

    def prepare(self, owner, key, proposal, inventory, *, plan_id=None, expected_revision=None,
                request_reference=None):
        _text(owner)
        _text(key)
        if request_reference is not None:
            _text(request_reference)
        request = _json({'proposal': asdict(proposal), 'plan_id': plan_id,
                         'expected_revision': expected_revision, 'request_reference': request_reference})
        with self._db() as db:
            previous = db.execute('SELECT proposal,record FROM model_plans WHERE owner=? AND request_key=?',
                                  (owner, key)).fetchone()
            if previous:
                if previous['proposal'] != request:
                    raise ValueError('plan request key changed request')
                return json.loads(previous['record'])
            result = _selection(proposal.context, proposal.selection, inventory)
            if plan_id is None:
                if expected_revision is not None:
                    raise ValueError('unexpected plan revision')
                plan_id = hashlib.sha256(_json([owner, key]).encode()).hexdigest()
                revision = 1
            else:
                latest = db.execute('SELECT MAX(revision) FROM model_plans WHERE owner=? AND id=?',
                                    (owner, plan_id)).fetchone()[0]
                if latest is None or type(expected_revision) is not int or latest != expected_revision:
                    raise ValueError('plan revision conflict or wrong owner')
                revision = latest + 1
            record = {**result, 'plan_id': plan_id, 'revision': revision,
                      'proposal': asdict(proposal), 'inventory': asdict(inventory),
                      'default_source': inventory.default_source if proposal.selection.model == 'inherit' else None,
                      'default_observation_revision': inventory.default_revision if proposal.selection.model == 'inherit' else None}
            db.execute('INSERT INTO model_plans VALUES(?,?,?,?,?,?)',
                       (owner, plan_id, revision, key, request, _json(record)))
            return json.loads(_json(record))

    def validate(self, owner, plan_id, revision, current_context, current_inventory, *, substantive=False):
        with self._db() as db:
            record = self._read(db, owner, plan_id, revision)
            latest = db.execute('SELECT MAX(revision) FROM model_plans WHERE owner=? AND id=?',
                                (owner, plan_id)).fetchone()[0]
        if revision != latest or record['proposal']['context'] != json.loads(_json(asdict(current_context))):
            raise ValueError('stale plan revision or request binding')
        selection = Selection(**record['proposal']['selection'])
        if selection.model == 'inherit' and (
            record['resolved_model_id'], record['default_source'], record['default_observation_revision']
        ) != (current_inventory.default_model, current_inventory.default_source, current_inventory.default_revision):
            raise ValueError('stale observed target default; new plan revision required')
        result = _selection(current_context, selection, current_inventory)
        if substantive and result['status'] != 'ready':
            raise ValueError('unresolved default; native preparation and new revision required')
        return {**result, 'plan_id': plan_id, 'revision': revision}
