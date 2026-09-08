from dataclasses import replace

import pytest
from neurath.providers.model_planning import (
    Constraints,
    Inventory,
    ModelInfo,
    ModelPlanStore,
    PlanContext,
    PlanProposal,
    Selection,
)


def fixture_values():
    info = ModelInfo('model-a', ('tools',), ('high',), 32000, 2.0, 500)
    inventory = Inventory('codex', 'local', 'native-model-list', 'inventory-1', (info,),
                          'model-a', 'host-config', 'default-1')
    context = PlanContext('assignment-digest', 1, 'codex', 'local', 'policy-digest', 'mapping-1')
    proposal = PlanProposal(context, Selection('inherit', 'high'), 'complex',
                            ('Permission changes require independent verification.',),
                            'high', 'Known tools and reasoning support.', (),
                            ('assignment changes', 'availability changes'))
    return inventory, proposal


def test_durable_replay_and_owner_fence(tmp_path):
    inventory, proposal = fixture_values()
    path = tmp_path / 'plans.sqlite3'
    store = ModelPlanStore(path)
    record = store.prepare('owner', 'key', proposal, inventory)
    reopened = ModelPlanStore(path)
    assert reopened.read('owner', record['plan_id'], 1) == record
    assert reopened.prepare('owner', 'key', proposal, replace(inventory, models=())) == record
    with pytest.raises(ValueError, match='owner'):
        reopened.read('other', record['plan_id'], 1)
    with pytest.raises(ValueError, match='key'):
        reopened.prepare('owner', 'key', replace(proposal, rationale='changed'), inventory)


def test_revisions_require_compare_and_swap(tmp_path):
    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    first = store.prepare('owner', 'one', proposal, inventory)
    changed = replace(proposal, selection=Selection('model-a', 'high'))
    second = store.prepare('owner', 'two', changed, inventory,
                           plan_id=first['plan_id'], expected_revision=1)
    assert second['revision'] == 2
    with pytest.raises(ValueError, match='revision'):
        store.prepare('owner', 'three', changed, inventory,
                      plan_id=first['plan_id'], expected_revision=1)
    with pytest.raises(ValueError, match='stale'):
        store.validate('owner', first['plan_id'], 1, proposal.context, inventory)


@pytest.mark.parametrize('field,value', [
    ('assignment_digest', 'changed'), ('assignment_revision', 2), ('provider', 'claude-code'),
    ('host', 'remote'), ('policy_digest', 'changed'), ('policy_mapping_revision', 'mapping-2'),
    ('constraints', Constraints(required_capabilities=('vision',))),
])
def test_binding_changes_make_plan_stale(tmp_path, field, value):
    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    record = store.prepare('owner', 'key', proposal, inventory)
    with pytest.raises(ValueError, match='stale'):
        store.validate('owner', record['plan_id'], 1, replace(proposal.context, **{field: value}), inventory)


def test_inventory_refresh_is_not_expiry_but_invalidating_facts_are(tmp_path):
    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    record = store.prepare('owner', 'key', proposal, inventory)
    refreshed = replace(inventory, revision='inventory-2', observed_at=9999999999)
    assert store.validate('owner', record['plan_id'], 1, proposal.context, refreshed)['status'] == 'ready'
    with pytest.raises(ValueError, match='default'):
        store.validate('owner', record['plan_id'], 1, proposal.context,
                       replace(refreshed, default_revision='default-2'))
    with pytest.raises(ValueError, match='unavailable'):
        store.validate('owner', record['plan_id'], 1, proposal.context, replace(refreshed, models=()))


@pytest.mark.parametrize('constraints', [
    Constraints(explicit_model='other'), Constraints(allowed_providers=('claude-code',)),
    Constraints(required_capabilities=('vision',)), Constraints(min_context_tokens=64000),
    Constraints(max_input_price_per_million=1), Constraints(max_latency_ms=100),
])
def test_hard_constraints_block_creation(tmp_path, constraints):
    inventory, proposal = fixture_values()
    proposal = replace(proposal, context=replace(proposal.context, constraints=constraints))
    with pytest.raises(ValueError):
        ModelPlanStore(tmp_path / 'plans.sqlite3').prepare('owner', 'key', proposal, inventory)


def test_unknown_price_is_not_zero_and_reasoning_not_assumed(tmp_path):
    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    unknown = replace(inventory, models=(replace(inventory.models[0], input_price_per_million=None),))
    limited = replace(proposal, context=replace(proposal.context,
                      constraints=Constraints(max_input_price_per_million=100)))
    with pytest.raises(ValueError, match='price'):
        store.prepare('owner', 'price', limited, unknown)
    with pytest.raises(ValueError, match='reasoning'):
        store.prepare('owner', 'reasoning', replace(proposal, selection=Selection('model-a', 'ultra')), inventory)


def test_unresolved_default_only_allows_constraint_free_preparation(tmp_path):
    inventory, proposal = fixture_values()
    inventory = replace(inventory, models=(), available=False, default_model=None)
    proposal = replace(proposal, selection=Selection('inherit'))
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    record = store.prepare('owner', 'key', proposal, inventory)
    assert record['status'] == 'preparation-only'
    assert record['resolved_model_id'] is None
    assert record['default_source'] == 'host-config'
    assert record['default_observation_revision'] == 'default-1'
    with pytest.raises(ValueError, match='unresolved'):
        store.validate('owner', record['plan_id'], 1, proposal.context, inventory, substantive=True)
    with pytest.raises(ValueError):
        store.prepare('owner', 'fixed', replace(proposal, selection=Selection('model-a')), inventory)
    constrained = replace(proposal, context=replace(proposal.context,
                          constraints=Constraints(required_capabilities=('tools',))))
    with pytest.raises(ValueError, match='unresolved'):
        store.prepare('owner', 'hard', constrained, inventory)


def test_inventory_target_and_structural_validation(tmp_path):
    inventory, proposal = fixture_values()
    with pytest.raises(ValueError, match='target'):
        ModelPlanStore(tmp_path / 'plans.sqlite3').prepare('owner', 'key', proposal,
                                                        replace(inventory, provider='claude-code'))
    with pytest.raises(ValueError):
        replace(proposal, difficulty='genius')
    with pytest.raises(ValueError):
        replace(proposal, evidence=())
    with pytest.raises(ValueError):
        replace(proposal.context, assignment_revision=True)
    with pytest.raises(ValueError):
        Constraints(max_input_price_per_million=float('nan'))


def test_failed_proposal_does_not_consume_request_key(tmp_path):
    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    with pytest.raises(ValueError):
        store.prepare('owner', 'key', proposal, replace(inventory, models=()))
    assert store.prepare('owner', 'key', proposal, inventory)['revision'] == 1


def test_concurrent_identical_acceptance_is_durable_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    inventory, proposal = fixture_values()
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.prepare('owner', 'key', proposal, inventory), range(8)))
    assert all(item == results[0] for item in results)
    assert results[0]['revision'] == 1


def test_explicit_model_ignores_unrelated_target_default_change(tmp_path):
    inventory, proposal = fixture_values()
    proposal = replace(proposal, selection=Selection('model-a', 'high'))
    store = ModelPlanStore(tmp_path / 'plans.sqlite3')
    record = store.prepare('owner', 'key', proposal, inventory)
    assert store.validate('owner', record['plan_id'], 1, proposal.context,
                          replace(inventory, default_model='other', default_revision='default-2'))['status'] == 'ready'


@pytest.mark.parametrize('suffix', ['', '-journal', '-wal', '-shm'])
def test_database_symlinks_are_rejected(tmp_path, suffix):
    target = tmp_path / 'elsewhere'
    target.write_text('preserve')
    path = tmp_path / 'plans.sqlite3'
    (tmp_path / ('plans.sqlite3' + suffix)).symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        ModelPlanStore(path)
    assert target.read_text() == 'preserve'


def test_parent_symlink_and_oversized_lists_rejected(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        ModelPlanStore(link / 'plans.sqlite3')
    with pytest.raises(ValueError):
        Constraints(required_capabilities=tuple(str(i) for i in range(1000)))


def test_unknown_default_provenance_is_preserved_for_preparation(tmp_path):
    inventory, proposal = fixture_values()
    inventory = replace(inventory, models=(), available=False, default_model=None,
                        default_source=None, default_revision=None)
    proposal = replace(proposal, selection=Selection('inherit'))
    record = ModelPlanStore(tmp_path / 'plans.sqlite3').prepare('owner', 'key', proposal, inventory)
    assert record['status'] == 'preparation-only'
    assert record['default_source'] is None
    assert record['default_observation_revision'] is None
