"""Persistence integration tests use exclusively temporary databases."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import pytest
from sqlalchemy import select
from neurath.domain.errors import ConflictError
from neurath.domain.models import Criterion, Lease, Phase, Receipt, Task
from neurath.infrastructure import Database, StorageError
from neurath.infrastructure.models import CriterionEvidenceRow, TaskRow


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / 'ledger.sqlite3')
    db.initialize()
    yield db
    db.close()


def task(identity='task-1'):
    return Task(id=identity, owner_id='owner', source_id='source', goal='Keep provenance', criteria=[Criterion('criterion', 'Observed verification', ['evidence-1'], True)], phases=[Phase('phase', 'Verify', 'completed', ['evidence-1'])], delegation_ids=['delegation-1'])


def test_task_roundtrip_uses_structured_primary_state(database):
    original = task()
    with database.uow() as uow:
        uow.repo('task').add(original)
        uow.commit()
    with database.uow() as uow:
        assert uow.repo('task').get(original.id).to_dict() == original.to_dict()
        row = uow.session.get(TaskRow, original.id)
        assert row.owner_id == 'owner'
        assert row.extra == {}
        assert uow.session.scalar(select(CriterionEvidenceRow.evidence_id)) == 'evidence-1'
        assert len(uow.repo('task').list(owner_id='owner')) == 1
        assert uow.repo('task').list(owner_id='foreign') == []


def test_uncommitted_and_exception_transactions_roll_back(database):
    with database.uow() as uow:
        uow.repo('task').add(task())
    with pytest.raises(RuntimeError):
        with database.uow() as uow:
            uow.repo('task').add(task('other'))
            raise RuntimeError('abort')
    assert database.export_records()['task'] == []


def test_stale_cas_preserves_task_and_children(database):
    original = task()
    with database.uow() as uow:
        uow.repo('task').add(original)
        uow.commit()
    changed = deepcopy(original)
    changed.goal = 'New goal'
    changed.revision = 1
    with database.uow() as uow:
        uow.repo('task').save(changed, 0)
        uow.commit()
    original.goal = 'Stale overwrite'
    original.criteria = []
    original.revision = 1
    with pytest.raises(ConflictError):
        with database.uow() as uow:
            uow.repo('task').save(original, 0)
            uow.commit()
    with database.uow() as uow:
        assert uow.repo('task').get(original.id).to_dict() == changed.to_dict()


def test_receipt_and_mutation_commit_atomically_and_concurrently(database):
    def attempt(_):
        with database.uow() as uow:
            if uow.repo('receipt').get('same-request'):
                return False
            uow.repo('task').add(task())
            uow.repo('receipt').add(Receipt(id='same-request', actor_id='owner', command='task.create', body_hash='hash', result={'task_id': 'task-1'}))
            uow.commit()
            return True
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(attempt, range(4))) == 1
    assert len(database.export_records()['task']) == 1
    assert len(database.export_records()['receipt']) == 1


def test_lease_resource_exclusivity_and_monotonic_fencing(database):
    lease = Lease(id='lease-1', resource='workspace', owner_id='owner')
    with database.uow() as uow:
        uow.repo('lease').add(lease)
        uow.commit()
    with pytest.raises(ConflictError):
        with database.uow() as uow:
            uow.repo('lease').add(Lease(id='different-id', resource='workspace', owner_id='foreign'))
    with pytest.raises(ConflictError):
        with database.uow() as uow:
            uow.repo('lease').save(Lease(id=lease.id, revision=1, resource='workspace', owner_id='foreign', generation=2), 0)
    lease.active, lease.revision = False, 1
    with database.uow() as uow:
        uow.repo('lease').save(lease, 0)
        uow.commit()
    with pytest.raises(ConflictError):
        with database.uow() as uow:
            uow.repo('lease').save(Lease(id=lease.id, revision=2, resource='workspace', owner_id='owner', generation=1), 1)
    lease.owner_id, lease.generation, lease.active, lease.revision = 'foreign', 2, True, 2
    with database.uow() as uow:
        uow.repo('lease').save(lease, 1)
        uow.commit()
    assert database.export_records()['lease'][0]['generation'] == 2


def test_import_archive_is_atomic_lossless_and_idempotent(database):
    archive = {'schema': ['CREATE TABLE old(blob BLOB)'], 'rows': [{'bytes': {'base64': 'AAE='}, 'null': None}]}
    records = {'task': [task().to_dict()]}
    assert database.import_records(records, snapshot_id='snapshot', archive=archive) is True
    assert database.import_records(records, snapshot_id='snapshot', archive=archive) is False
    assert database.read_archive('snapshot') == archive
    with pytest.raises(ConflictError):
        database.import_records(records, snapshot_id='snapshot', archive={'different': True})
    colliding = task().to_dict()
    colliding['goal'] = 'collision'
    with pytest.raises(ConflictError):
        database.import_records({'task': [task('first').to_dict(), colliding]}, snapshot_id='failed', archive=archive)
    assert database.read_archive('failed') is None
    assert len(database.export_records()['task']) == 1


def test_read_only_export_does_not_change_database(database):
    database.import_records({'task': [task().to_dict()]})
    before = hashlib.sha256(database.path.read_bytes()).hexdigest()
    assert database.export_records()['task'][0]['goal'] == 'Keep provenance'
    assert hashlib.sha256(database.path.read_bytes()).hexdigest() == before


def test_database_path_and_parent_symlink_guards(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'db').touch()
    (tmp_path / 'link').symlink_to(real, target_is_directory=True)
    (tmp_path / 'db-link').symlink_to(real / 'db')
    for path in (tmp_path / 'link' / 'db', tmp_path / 'db-link'):
        with pytest.raises(StorageError):
            Database(path)


def test_archive_chunks_are_bounded_verified_and_reassembled(database, monkeypatch):
    import neurath.infrastructure.storage as storage
    from neurath.infrastructure.models import ArchiveChunkRow
    monkeypatch.setattr(storage, 'ARCHIVE_CHUNK_BYTES', 64)
    archive = {'rows': [hashlib.sha256(str(index).encode()).hexdigest() for index in range(100)]}
    database.import_records({}, snapshot_id='chunked', archive=archive)
    assert database.read_archive('chunked') == archive
    with database.uow() as uow:
        chunks = list(uow.session.scalars(select(ArchiveChunkRow).where(ArchiveChunkRow.archive_id == 'chunked')))
        assert len(chunks) > 1
        assert max(len(chunk.data) for chunk in chunks) <= 64
        uow.session.delete(chunks[-1])
        uow.commit()
    with pytest.raises(StorageError, match='integrity'):
        database.read_archive('chunked')


def test_revision_history_preserves_original_definition(database):
    original = task()
    original.source_ids = ['source']
    with database.uow() as uow:
        uow.repo('task').add(original)
        uow.commit()
    revised = deepcopy(original)
    revised.revision = 1
    revised.goal = 'Revised definition'
    revised.source_ids.append('revision-source')
    with database.uow() as uow:
        uow.repo('task').save(revised, 0)
        uow.commit()
    assert database.history('task', original.id) == [original.to_dict(), revised.to_dict()]
    assert database.export_records()['task'] == [revised.to_dict()]
