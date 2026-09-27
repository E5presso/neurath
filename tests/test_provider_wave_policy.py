"""DAG decisions are checked without databases, threads or native model calls."""
from copy import deepcopy

import pytest

from neurath.providers.wave_policy import descendants, normalize_entries, schedule


def queued(name, depends=()):
    return {'entry_id': name, 'depends_on': list(depends), 'run_id': None,
            'status': 'queued', 'consumption': None, 'generation': None, 'result_digest': None}


def completed(name):
    return queued(name) | {'run_id': 'run-' + name, 'status': 'completed', 'generation': 1,
        'result_digest': 'digest-' + name, 'consumption': {'run_id': 'run-' + name,
        'generation': 1, 'result_digest': 'digest-' + name, 'verdict': 'accepted'}}


def test_capacity_and_stable_order_include_all_unfinished_reservations():
    entries = [queued('a') | {'run_id': 'run-a', 'status': 'starting'}, queued('b'), queued('c')]
    assert schedule(entries, 2).ready == ('b',)
    assert schedule(entries, 1).ready == ()
    # Terminal work frees capacity even before the owner consumes its result.
    entries[0].update(status='completed')
    assert schedule(entries, 2).ready == ('b', 'c')


@pytest.mark.parametrize('changed', [
    {'consumption': None}, {'status': 'failed'}, {'generation': 2},
    {'run_id': 'retry-run'}, {'result_digest': 'changed-result'},
])
def test_stale_or_absent_consumption_never_unlocks_success_dependency(changed):
    parent = completed('parent') | changed
    decision = schedule([parent, queued('dependent', ['parent']), queued('independent')], 2)
    assert decision.ready == ('independent',)


def test_rejection_propagates_through_reverse_ordered_diamond_without_mutation():
    parent = completed('parent')
    parent['consumption']['verdict'] = 'rejected'
    entries = [queued('leaf', ['left', 'right']), queued('left', ['parent']),
               parent, queued('right', ['parent']), queued('independent')]
    before = deepcopy(entries)
    decision = schedule(entries, 4)
    assert decision.blocked == ('leaf', 'left', 'right')
    assert decision.ready == ('independent',)
    assert entries == before
    assert descendants(entries, {'parent'}) == {'parent', 'left', 'right', 'leaf'}


def test_exact_consumption_unlocks_all_ready_branches_in_admitted_order():
    entries = [queued('right', ['parent']), completed('parent'), queued('left', ['parent'])]
    assert schedule(entries, 2).ready == ('right', 'left')


@pytest.mark.parametrize('dependencies', [(['a'],), (['missing'],), (['b'], ['a']), (['a', 'a'],)])
def test_invalid_graphs_are_rejected_before_any_reservation(dependencies):
    entries = [{'entry_id': name, 'depends_on': depends, 'request': {}}
               for name, depends in zip(('a', 'b'), dependencies)]
    with pytest.raises(ValueError):
        normalize_entries(entries)


def test_forward_references_preserve_declared_dispatch_order():
    entries = [{'entry_id': 'later', 'depends_on': ['first'], 'request': {}},
               {'entry_id': 'first', 'depends_on': [], 'request': {}}]
    assert [entry.entry_id for entry in normalize_entries(entries)] == ['later', 'first']
