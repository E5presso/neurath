from dataclasses import replace

import pytest
from neurath.providers.permission_inheritance import inherit_policy, snapshot_from_evidence

CONTROL = {'filesystem': 'unrestricted', 'network': 'unrestricted',
           'tool_allowlist': [], 'tool_denylist': [], 'hooks': []}
CODEX = {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'},
         'collaboration_mode': 'default', 'approvals_reviewer': 'user'}


def snapshot(provider='codex', policy=None, controls=None):
    return snapshot_from_evidence(provider, policy if policy is not None else CODEX,
                                  source='native-turn', controls=CONTROL if controls is None else controls,
                                  controls_source='native-controls')


def test_broad_mapping_both_directions():
    forward = inherit_policy(snapshot(), 'claude-code')
    assert forward.status == 'mapped'
    assert forward.settings == {'permission_mode': 'bypassPermissions'}
    backward = inherit_policy(snapshot('claude-code', {'permission_mode': 'bypassPermissions'}), 'codex')
    assert backward.status == 'mapped'
    assert backward.settings['approval_policy'] == 'never'
    assert backward.settings['sandbox_policy'] == {'type': 'danger-full-access'}


@pytest.mark.parametrize('mode', ['plan', 'dontAsk', 'default', 'acceptEdits', 'auto', 'bypassPermissions'])
def test_same_claude_mode_and_controls_preserved(mode):
    controls = {**CONTROL, 'tool_denylist': ['Shell(unsafe)'], 'hooks': ['shared-hook-digest']}
    result = inherit_policy(snapshot('claude-code', {'permission_mode': mode}, controls), 'claude-code')
    assert result.status == 'mapped'
    assert result.settings == {'permission_mode': mode}
    assert result.controls == controls


def test_same_codex_keeps_exact_workspace_confinement():
    policy = {**CODEX, 'sandbox_policy': {'type': 'workspace-write', 'writable_roots': ['/workspace/shared'],
                                         'network_access': False, 'exclude_slash_tmp': True}}
    controls = {**CONTROL, 'filesystem': 'provider-native', 'network': 'restricted'}
    result = inherit_policy(snapshot(policy=policy, controls=controls), 'codex')
    assert result.status == 'mapped'
    assert result.settings == policy
    assert result.controls == controls


def test_restricted_intermediate_does_not_restore_root_scope():
    broad = inherit_policy(snapshot(), 'claude-code')
    assert broad.status == 'mapped'
    restricted = snapshot('claude-code', {'permission_mode': 'dontAsk'})
    result = inherit_policy(restricted, 'codex')
    assert result.status == 'blocked'
    assert 'permission_mode' in result.unsupported_dimensions
    assert result.settings == {}


@pytest.mark.parametrize('dimension,value', [('filesystem', 'restricted'), ('network', 'restricted'),
    ('tool_allowlist', ['Read']), ('tool_denylist', ['Shell(unsafe)']), ('hooks', ['provider-hook'])])
def test_cross_provider_restrictions_never_disappear(dimension, value):
    result = inherit_policy(snapshot(controls={**CONTROL, dimension: value}), 'claude-code')
    assert result.status == 'blocked'
    assert dimension in result.unsupported_dimensions


def test_verified_common_hook_can_be_preserved_separately():
    controls = {**CONTROL, 'hooks': ['common-hook-digest']}
    result = inherit_policy(snapshot(controls=controls), 'claude-code', target_controls=controls)
    assert result.status == 'mapped'
    assert result.controls['hooks'] == ['common-hook-digest']


def test_claude_mode_does_not_attest_os_confinement():
    native = snapshot_from_evidence('claude-code', {'permission_mode': 'bypassPermissions',
                                   'sandbox_observation': 'unobserved'}, source='native-hook')
    result = inherit_policy(native, 'codex')
    assert result.status == 'blocked'
    assert 'unobserved:filesystem' in result.unsupported_dimensions
    assert 'unobserved:network' in result.unsupported_dimensions


def test_requested_mismatch_does_not_override_inheritance():
    result = inherit_policy(snapshot(), 'codex', requested={'approval_policy': 'on-request'})
    assert result.status == 'blocked'
    assert result.unsupported_dimensions == ('requested:approval_policy',)
    assert result.settings == {}
    assert inherit_policy(snapshot(), 'codex', requested={'approval_policy': 'never'}).status == 'mapped'


def test_unknown_and_unobserved_dimensions_block():
    assert 'future_policy' in inherit_policy(snapshot(policy={**CODEX, 'future_policy': True}), 'codex').unsupported_dimensions
    missing = snapshot_from_evidence('codex', CODEX, source=None, controls=CONTROL, controls_source='native')
    assert 'unobserved:approval_policy' in inherit_policy(missing, 'codex').unsupported_dimensions
    with pytest.raises(ValueError):
        snapshot('unsupported')


def test_snapshot_and_result_do_not_expose_mutable_policy_storage():
    policy = {**CODEX, 'sandbox_policy': {'type': 'danger-full-access'}}
    original = snapshot(policy=policy)
    policy['sandbox_policy']['type'] = 'read-only'
    result = inherit_policy(original, 'codex')
    assert result.settings['sandbox_policy']['type'] == 'danger-full-access'
    result.settings['sandbox_policy']['type'] = 'read-only'
    assert result.settings['sandbox_policy']['type'] == 'danger-full-access'
    assert replace(original, fields=()).provider == 'codex'


def test_target_may_not_add_silent_restrictions():
    result = inherit_policy(snapshot(), 'claude-code', target_controls={**CONTROL, 'network': 'restricted'})
    assert result.status == 'blocked'
    assert 'target:network' in result.unsupported_dimensions


def test_source_planning_and_non_broad_approval_have_no_guessed_alias():
    for policy, dimension in [({**CODEX, 'collaboration_mode': 'plan'}, 'collaboration_mode'),
                              ({**CODEX, 'approval_policy': 'on-request'}, 'approval_policy')]:
        result = inherit_policy(snapshot(policy=policy), 'claude-code')
        assert result.status == 'blocked'
        assert dimension in result.unsupported_dimensions
