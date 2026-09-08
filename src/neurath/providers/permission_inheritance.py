"""Pure permission-envelope mapping; snapshots never establish native authority.

The invoking wrapper verifies the immediate creator's current turn and each
observation source before capture, and checks target application before dispatch.
Controls describe known provider restrictions, not ambient OS access. Explicit
unobserved filesystem/network values remain unknown and are not an automatic
barrier to native mode inheritance. Known restrictions still require preservation.
Controls are normalized semantic observations, not raw provider rule syntax.
Target controls, when supplied, must be independently verified equivalents (for
example a shared hook contract), never a caller's assertion that tools are safe.
"""

import json
from dataclasses import dataclass

PROVIDERS = ('codex', 'claude-code')
MAPPING_REVISION = 'permission-inheritance-v2'
NATIVE_FIELDS = {
    'codex': ('approval_policy', 'sandbox_policy', 'collaboration_mode', 'approvals_reviewer'),
    'claude-code': ('permission_mode',),
}
CONTROL_FIELDS = ('filesystem', 'network', 'tool_allowlist', 'tool_denylist', 'hooks')
METADATA = {'turn_id', 'cwd', 'host', 'session', 'actor', 'turn', 'tool_use_id', 'source',
            'sandbox_observation', 'user_prompt_receipt'}
CLAUDE_MODES = ('plan', 'dontAsk', 'default', 'acceptEdits', 'auto', 'bypassPermissions')


def _json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > 131072:
        raise ValueError('permission snapshot exceeds storage bound')
    return encoded


@dataclass(frozen=True)
class ObservedField:
    name: str
    value_json: str
    source: str | None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or len(self.name) > 256:
            raise ValueError('invalid observation field')
        if self.source is not None and (not isinstance(self.source, str) or not self.source or len(self.source) > 4096):
            raise ValueError('invalid observation source')
        _json(json.loads(self.value_json))

    @property
    def value(self):
        return json.loads(self.value_json)


@dataclass(frozen=True)
class PolicySnapshot:
    provider: str
    fields: tuple[ObservedField, ...]

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise ValueError('unsupported provider')
        if not isinstance(self.fields, tuple) or len(self.fields) > 64 or any(not isinstance(f, ObservedField) for f in self.fields):
            raise ValueError('invalid policy observations')
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError('duplicate policy observations')


@dataclass(frozen=True)
class MappingResult:
    source_provider: str
    target_provider: str
    status: str
    settings_json: str
    controls_json: str
    unsupported_dimensions: tuple[str, ...]
    mapping_revision: str = MAPPING_REVISION

    @property
    def settings(self):
        return json.loads(self.settings_json)

    @property
    def controls(self):
        return json.loads(self.controls_json)


def snapshot_from_evidence(provider, evidence, *, source, controls=None, controls_source=None):
    """Capture already verified readiness evidence without interpreting identity.

    Source labels are reference metadata, not proof. Missing controls remain
    missing; notably Claude permissionMode never proves OS confinement.
    """
    if not isinstance(evidence, dict) or controls is not None and not isinstance(controls, dict):
        raise TypeError('policy evidence and controls must be mappings')
    fields = [ObservedField(name, _json(value), source)
              for name, value in evidence.items() if name not in METADATA]
    fields.extend(ObservedField('controls.' + name, _json(value), controls_source)
                  for name, value in (controls or {}).items())
    return PolicySnapshot(provider, tuple(fields))


def _native_dimensions(provider, settings):
    invalid = [name for name in settings if name not in NATIVE_FIELDS[provider]]
    if provider == 'claude-code':
        if settings.get('permission_mode') not in CLAUDE_MODES:
            invalid.append('permission_mode')
    else:
        approval = settings.get('approval_policy')
        if not isinstance(approval, dict) and approval not in ('never', 'on-request', 'untrusted', 'on-failure'):
            invalid.append('approval_policy')
        sandbox = settings.get('sandbox_policy')
        if not isinstance(sandbox, dict) or sandbox.get('type') not in (
            'read-only', 'workspace-write', 'danger-full-access', 'external-sandbox'
        ):
            invalid.append('sandbox_policy')
        if settings.get('collaboration_mode') not in (None, 'default', 'plan'):
            invalid.append('collaboration_mode')
        if settings.get('approvals_reviewer') not in (None, 'user', 'auto_review'):
            invalid.append('approvals_reviewer')
    return invalid


def inherit_policy(creator, target_provider, *, requested=None, target_controls=None):
    """Return exact inherited settings or explicit blocked dimensions, without I/O.

    A mapped result is a preparation instruction, never permission to dispatch.
    requested is an equality assertion on supplied settings; it cannot widen or
    narrow inheritance. An authorized policy change needs a separate flow.
    """
    if not isinstance(creator, PolicySnapshot):
        raise TypeError('creator must be a PolicySnapshot')
    if target_provider not in PROVIDERS:
        raise ValueError('unsupported target provider')
    if target_controls is not None and not isinstance(target_controls, dict):
        raise TypeError('target controls must be a mapping')
    if requested is not None and not isinstance(requested, dict):
        raise TypeError('requested must be a mapping')
    fields = {item.name: item for item in creator.fields}
    settings = {name: item.value for name, item in fields.items() if not name.startswith('controls.')}
    controls = {name.removeprefix('controls.'): item.value for name, item in fields.items()
                if name.startswith('controls.')}
    unsupported = _native_dimensions(creator.provider, settings)
    required = ('approval_policy', 'sandbox_policy') if creator.provider == 'codex' else ('permission_mode',)
    for name in (*required, *('controls.' + name for name in CONTROL_FIELDS)):
        if name not in fields or fields[name].source is None:
            unsupported.append('unobserved:' + name.removeprefix('controls.'))
    for name, item in fields.items():
        if item.source is None:
            unsupported.append('unobserved:' + name.removeprefix('controls.'))
    for name, value in controls.items():
        if name not in CONTROL_FIELDS:
            unsupported.append(name)
        elif name in ('filesystem', 'network'):
            if value not in ('unrestricted', 'provider-native', 'restricted', 'unobserved'):
                unsupported.append('unobserved:' + name)
        elif not isinstance(value, list) or len(value) > 128 or any(not isinstance(v, str) or not v for v in value):
            unsupported.append(name)
    if creator.provider != target_provider:
        for name in ('filesystem', 'network'):
            if controls.get(name) in ('provider-native', 'restricted'):
                unsupported.append(name)
        if target_controls is not None:
            for name in ('filesystem', 'network'):
                if target_controls.get(name) in ('provider-native', 'restricted'):
                    unsupported.append('target:' + name)
        for name in ('tool_allowlist', 'tool_denylist', 'hooks'):
            if controls.get(name) and (target_controls is None or target_controls.get(name) != controls[name]):
                unsupported.append(name)
        if creator.provider == 'codex':
            if settings.get('approval_policy') != 'never':
                unsupported.append('approval_policy')
            if settings.get('sandbox_policy') != {'type': 'danger-full-access'}:
                unsupported.append('sandbox_policy')
            if settings.get('collaboration_mode') == 'plan':
                unsupported.append('collaboration_mode')
            settings = {'permission_mode': 'bypassPermissions'}
        else:
            if settings.get('permission_mode') != 'bypassPermissions':
                unsupported.append('permission_mode')
            settings = {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'},
                        'collaboration_mode': 'default'}
    if target_controls is not None:
        for name in set(CONTROL_FIELDS) | set(target_controls):
            if name in ('filesystem', 'network') and 'unobserved' in (controls.get(name), target_controls.get(name)):
                continue  # Unknown is retained, never converted to unrestricted.
            if name not in target_controls or name not in controls or target_controls[name] != controls[name]:
                unsupported.append('target:' + name)
    for name, value in (requested or {}).items():
        if name not in settings or settings[name] != value:
            unsupported.append('requested:' + name)
    unsupported = tuple(sorted(set(unsupported)))
    return MappingResult(creator.provider, target_provider, 'blocked' if unsupported else 'mapped',
                         _json({} if unsupported else settings), _json(controls), unsupported)
