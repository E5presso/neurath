"""Synchronization remains atomic and bounded as completed commands accumulate."""
import json
import subprocess
from contextlib import contextmanager

import pytest

from neurath.memory.learning import Learning
from neurath.memory.store import MemoryConflict, ProjectMemory
from neurath.memory.transcript import synchronize


def setup(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    memory = ProjectMemory(tmp_path)
    path = tmp_path / 'native.jsonl'
    return memory, path


def sync(memory, path, commands):
    path.write_text('\n'.join(json.dumps({'type': 'event_msg', 'payload': {
        'type': 'item_completed', 'thread_id': 'own', 'item': {
            'type': 'CommandExecution', 'id': identity, 'command': ['/bin/sh', '-c', command],
            'cwd': str(memory.worktree), 'status': 'completed', 'exit_code': code}}})
        for identity, command, code in commands))
    synchronize(memory, memory.worktree, 'codex', 'own',
                {'host': 'codex', 'transcript': str(path)})


def test_sync_uses_bounded_connections_for_first_ingestion_and_replay(tmp_path):
    memory, path = setup(tmp_path)
    original = memory.connection
    connections = []

    @contextmanager
    def counted():
        connections.append(1)
        with original() as db:
            yield db

    memory.connection = counted
    commands = [(str(i), f'echo {i}', 0) for i in range(100)]
    for _ in range(2):
        connections.clear()
        sync(memory, path, commands)
        assert len(connections) <= 3
    assert memory.count() == 100


def test_conflicting_replay_rolls_back_new_events_and_learning(tmp_path):
    memory, path = setup(tmp_path)
    sync(memory, path, [('existing', 'echo original', 0)])
    with pytest.raises(MemoryConflict):
        sync(memory, path, [('failure', 'pytest -q', 127),
                            ('recovery', 'uv run pytest -q', 0),
                            ('existing', 'echo changed', 0)])
    assert memory.count() == 1
    assert Learning(memory).status() == []


def test_batched_learning_preserves_order_and_replay_idempotency(tmp_path):
    memory, path = setup(tmp_path)
    commands = [('failure', 'pytest -q', 127), ('recovery', 'uv run pytest -q', 0)]
    sync(memory, path, commands)
    engine = Learning(memory)
    before = engine.status()
    assert len(before) == 1
    assert before[0]['status'] == 'candidate'
    history = engine.history(before[0]['id'])
    sync(memory, path, commands)
    assert engine.status() == before
    assert engine.history(before[0]['id']) == history
