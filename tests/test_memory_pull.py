"""Receiver-owned pull preserves source history and imports only unfinished work."""
import json
import subprocess
import pytest

pytest_plugins = ["tests.test_task_ledger_service"]

@pytest.fixture
def migration(service, monkeypatch):
    from neurath.memory.migration import PullMigration
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.task_service import TaskService
    from tests.test_task_ledger_service import item
    source, kernel, sk = service
    root = source.worktree
    subprocess.run(['git','init','-q',str(root)],check=True)
    defined = source.define([item('done'),item('remaining')],expected_revision=0,key='source-define')
    source.resolve(defined['tasks'][0]['id'],expected_revision=1,expected_task_revision=1,
        key='source-done',status='succeeded',summary='Already completed',references=['result:original'])
    kernel.apply(sk.SessionStarted(session_id=sk.SessionId('receiver'),resume_id=sk.ResumeId('receiver'),
        root_actor_id=sk.ActorId('receiver-owner'),runtime=sk.SessionRuntime.CLAUDE_CODE,idempotency_key='receiver-start'))
    kernel.apply(sk.ForegroundTurnProvisioned(session_id=sk.SessionId('receiver'),actor_id=sk.ActorId('receiver-owner'),idempotency_key='receiver-provision'))
    kernel.apply(sk.ForegroundTurnPrompted(session_id=sk.SessionId('receiver'),actor_id=sk.ActorId('receiver-owner'),
        vendor_turn_id='receiver-turn',prompt_digest='b'*64,idempotency_key='receiver-prompt'))
    handle = StateHandle.attach(sk.SessionLocator(root),RuntimeIdentityBinding(runtime=sk.SessionRuntime.CLAUDE_CODE,
        session_id=sk.SessionId('receiver'),actor_id=sk.ActorId('receiver-owner'),root_actor_id=sk.ActorId('receiver-owner')))
    target = TaskService(handle)
    monkeypatch.setattr('neurath.memory.migration.observe_source',lambda *a,**k:{
        'worktree':str(root),'quiescent':True,'pending_tools':[],
        'transcript':{'status':'unavailable','entries':[]},'fingerprint':'test-observed-closed'})
    from neurath.memory.store import ProjectMemory
    memory = ProjectMemory(root)
    memory.record('codex','one','original-prompt','prompt','Finish the remaining feature')
    memory.record('codex','unrelated','other-prompt','prompt','Must never appear in source pull')
    return PullMigration(target), source, target

def test_preview_is_exact_source_and_never_changes_ownership(migration):
    pull, source, target = migration
    before = source.list()
    preview = pull.preview('codex','one',key='preview')
    assert preview['authority']=='reference-only'
    assert len(preview['source_tasks'])==2
    assert all(e['session']=='one' for e in preview['memory'])
    assert source.list()==before
    assert target.list()['tasks']==[]

def test_adopt_retains_completed_history_and_is_idempotent(migration):
    pull, source, target = migration
    before = source.list()
    preview = pull.preview('codex','one',key='preview')
    result = pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    assert result['status']=='adopted'
    assert len(target.list()['tasks'])==1
    assert target.list()['tasks'][0]['definition']['key'].startswith('pull:')
    assert target.list()['tasks'][0]['status']=='pending'
    assert target.list()['tasks'][0]['id'] != before['tasks'][1]['id']
    assert source.list()['tasks']==before['tasks']
    assert pull.adopt(preview['reference'],expected_revision=0,key='adopt')==result

def test_live_source_is_preview_only(migration,monkeypatch):
    pull, source, target = migration
    monkeypatch.setattr('neurath.memory.migration.observe_source',lambda *a,**k:{
        'worktree':str(source.worktree),'quiescent':False,'pending_tools':['native-tool'],
        'transcript':{'status':'partial','entries':[]},'fingerprint':'live'})
    preview=pull.preview('codex','one',key='live-preview')
    with pytest.raises(ValueError,match='source.*quiescent'):
        pull.adopt(preview['reference'],expected_revision=0,key='adopt-live')
    assert target.list()['tasks']==[]

def test_source_revision_change_rejects_old_preview(migration):
    from tests.test_task_ledger_service import item
    pull, source, target = migration
    preview=pull.preview('codex','one',key='preview')
    source.define([item('later')],expected_revision=2,key='later')
    with pytest.raises(ValueError,match='source.*changed'):
        pull.adopt(preview['reference'],expected_revision=0,key='stale-adopt')
    assert target.list()['tasks']==[]

def test_source_cannot_resume_mutations_or_reclaim_after_receiver_release(migration):
    from tests.test_task_ledger_service import item
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeClaimInvalid, WorktreeIdentityResolver
    from scripts.agent_harness.task_ledger import TaskLedgerError
    pull, source, target = migration
    p=pull.preview('codex','one',key='preview')
    pull.adopt(p['reference'],expected_revision=0,key='adopt')
    canonical=WorktreeIdentityResolver().resolve(source.worktree)
    registry=WorktreeRegistry(SessionLocator(source.worktree))
    registry.release(registry.get(canonical.worktree_id))
    with pytest.raises(TaskLedgerError,match='migrated'):
        source.define([item('duplicate')],expected_revision=2,key='source-resume')
    with pytest.raises(WorktreeClaimInvalid,match='migrated'):
        registry.claim(WorktreeClaim(worktree_id=canonical.worktree_id,path=canonical.path,
            session_id=source.handle.session_id,actor_id=source.handle.actor_id))
    assert source.list()['superseded_by']['receiver_session']=='receiver'

def test_actual_source_lease_moves_atomically_and_rejects_old_token(migration):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeIdentityResolver, WorktreeLeaseConflict
    pull, source, target=migration
    identity=WorktreeIdentityResolver().resolve(source.worktree)
    registry=WorktreeRegistry(SessionLocator(source.worktree))
    original=registry.claim(WorktreeClaim(worktree_id=identity.worktree_id,path=identity.path,
        session_id=source.handle.session_id,actor_id=source.handle.actor_id))
    preview=pull.preview('codex','one',key='preview')
    result=pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    current=registry.get(identity.worktree_id)
    assert current.session_id==target.handle.session_id
    assert current.lease_epoch==original.lease_epoch+1
    assert current.fencing_token!=original.fencing_token
    assert current.transition_id==result['migration_id']
    with pytest.raises(WorktreeLeaseConflict):registry.release(original)

def test_fault_after_target_import_rolls_back_every_domain(migration,monkeypatch):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeIdentityResolver
    pull,source,target=migration
    identity=WorktreeIdentityResolver().resolve(source.worktree)
    registry=WorktreeRegistry(SessionLocator(source.worktree))
    original=registry.claim(WorktreeClaim(worktree_id=identity.worktree_id,path=identity.path,
        session_id=source.handle.session_id,actor_id=source.handle.actor_id))
    preview=pull.preview('codex','one',key='preview')
    replace=WorktreeRegistry.replace_transaction
    def fail(*a,**k):
        replace(*a,**k)
        raise RuntimeError('injected handoff failure')
    monkeypatch.setattr(WorktreeRegistry,'replace_transaction',fail)
    with pytest.raises(RuntimeError,match='injected'):
        pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    assert target.list()['tasks']==[]
    assert registry.get(identity.worktree_id).fencing_token==original.fencing_token
    with source.database.transaction() as tx:
        assert tx.get('session-migration','one') is None

def test_pending_dependency_mapping_uses_new_ids(migration):
    from tests.test_task_ledger_service import item
    pull,source,target=migration
    old=source.list()['tasks'][1]['id']
    dependent=item('dependent');dependent['dependencies']=[old]
    source.define([dependent],expected_revision=2,key='dependent')
    preview=pull.preview('codex','one',key='preview')
    result=pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    tasks=target.list()['tasks']
    new_dep=next(t for t in tasks if t['definition']['title']=='Fix dependent')
    assert new_dep['definition']['dependencies']==[result['task_mapping'][old]]

def test_lease_change_rejects_preview_even_if_task_revision_is_unchanged(migration):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeIdentityResolver
    pull,source,target=migration
    preview=pull.preview('codex','one',key='preview')
    identity=WorktreeIdentityResolver().resolve(source.worktree)
    registry=WorktreeRegistry(SessionLocator(source.worktree))
    registry.claim(WorktreeClaim(worktree_id=identity.worktree_id,path=identity.path,
        session_id=source.handle.session_id,actor_id=source.handle.actor_id))
    with pytest.raises(ValueError,match='lease changed'):
        pull.adopt(preview['reference'],expected_revision=0,key='stale-lease')
    assert target.list()['tasks']==[]

def test_active_peer_assignment_is_preview_only_and_completion_requires_fresh_pull(migration):
    from neurath.agents.store import MessageStore, AgentIdentity
    from neurath.agents.lifecycle import TaskLifecycle
    pull,source,target=migration
    store=MessageStore(source.worktree)
    store.register(AgentIdentity('codex','one','owner'))
    store.register(AgentIdentity('claude-code','peer','peer-owner'))
    tasks=TaskLifecycle(store)
    task=tasks.bind('codex:one','claude-code:peer',key='delegated',transport='peer')
    tasks.emit('claude-code:peer',task['id'],'started',key='peer-start')
    preview=pull.preview('codex','one',key='preview')
    assert preview['communications']['peer_tasks'][0]['state']=='started'
    with pytest.raises(ValueError,match='peer assignments'):
        pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    tasks.emit('claude-code:peer',task['id'],'completed',key='peer-done')
    with pytest.raises(ValueError,match='source state changed'):
        pull.adopt(preview['reference'],expected_revision=0,key='old-preview')
    assert target.list()['tasks']==[]

def test_claim_reader_and_atomic_adoption_do_not_invert_locks(tmp_path):
    import sys
    code = '''
import sys,threading
from pathlib import Path
from pytest import MonkeyPatch
from tests.test_task_ledger_service import service
from tests.test_memory_pull import migration
from neurath.runtime.engine import activate
activate()
from scripts.agent_harness.session_kernel import SessionLocator
from scripts.agent_harness.worktree_registry import WorktreeRegistry,WorktreeIdentityResolver,WorktreeClaim
mp=MonkeyPatch()
Path(sys.argv[1]).mkdir()
pull,source,target=migration.__wrapped__(service.__wrapped__(Path(sys.argv[1])),mp)
identity=WorktreeIdentityResolver().resolve(source.worktree)
registry=WorktreeRegistry(SessionLocator(source.worktree))
registry.claim(WorktreeClaim(worktree_id=identity.worktree_id,path=identity.path,session_id=source.handle.session_id,actor_id=source.handle.actor_id))
preview=pull.preview('codex','one',key='preview')
db_held,file_held,proceed=threading.Event(),threading.Event(),threading.Event()
original=registry._read_claim
def read(*args):
    file_held.set()
    assert proceed.wait(3)
    return original(*args)
registry._read_claim=read
errors=[]
def reader():
    try:
        assert db_held.wait(3)
        registry.get(identity.worktree_id)
    except BaseException as e:errors.append(repr(e))
def adopter():
    try:
        with source.database.transaction():
            db_held.set()
            assert file_held.wait(3)
            proceed.set()
            pull.adopt(preview['reference'],expected_revision=0,key='adopt')
    except BaseException as e:errors.append(repr(e))
threads=[threading.Thread(target=f,daemon=True) for f in (reader,adopter)]
for t in threads:t.start()
for t in threads:t.join(5)
assert not any(t.is_alive() for t in threads), 'worktree/SQLite lock inversion'
assert not errors,errors
print('MIGRATION_LOCK_ORDER_OK')
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path/'fixture')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'MIGRATION_LOCK_ORDER_OK' in result.stdout

@pytest.mark.parametrize('record_count', [1, 30])
def test_large_preview_is_bounded_and_full_document_can_be_read(migration, record_count):
    from neurath.memory.store import canonical, ProjectMemory
    pull,source,target=migration
    memory=ProjectMemory(source.worktree)
    for index in range(record_count):
        memory.record('codex','one','long-'+str(index),'assistant','진행 기록 '*2000)
    result=pull.preview('codex','one',key='large-preview')
    if record_count == 1:
        assert 8000 < len(canonical(result).encode()) < 60000
    view=pull.response_view(result)
    assert view['preview_limited'] and len(canonical(view).encode())<=8000
    parts=[]
    offset=0
    while offset is not None:
        page=pull.read(result['reference'],offset)
        assert len(canonical(page).encode()) <= 8000
        parts.append(page['json_fragment'])
        offset=page['next_offset']
    assert json.loads(''.join(parts))==result

def test_adoption_serializes_with_source_release(migration,monkeypatch):
    from contextlib import contextmanager
    from queue import Queue
    from threading import Event, Thread, current_thread
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeClaim, WorktreeIdentityResolver, WorktreeNotClaimed
    pull,source,target=migration
    identity=WorktreeIdentityResolver().resolve(source.worktree)
    registry=WorktreeRegistry(SessionLocator(source.worktree))
    original=registry.claim(WorktreeClaim(worktree_id=identity.worktree_id,path=identity.path,
        session_id=source.handle.session_id,actor_id=source.handle.actor_id))
    preview=pull.preview('codex','one',key='preview')
    releasing,proceed=Event(),Event()
    progress=Queue()
    errors=[]
    delete=registry._delete_locked
    def paused_delete(*a,**k):
        releasing.set()
        assert proceed.wait(5)
        return delete(*a,**k)
    monkeypatch.setattr(registry,'_delete_locked',paused_delete)
    admission=WorktreeRegistry.terminal_admission
    @contextmanager
    def tracked_admission(self,worktree_id):
        if current_thread().name=='adopter':progress.put('waiting-for-lease')
        with admission(self,worktree_id):yield
    monkeypatch.setattr(WorktreeRegistry,'terminal_admission',tracked_admission)
    def release():
        try:registry.release(original)
        except BaseException as e:errors.append(e)
    def adopt():
        try:
            pull.adopt(preview['reference'],expected_revision=0,key='adopt')
            progress.put('incorrectly-adopted')
        except BaseException as e:errors.append(e)
    first=Thread(target=release,daemon=True)
    second=Thread(target=adopt,name='adopter',daemon=True)
    first.start()
    assert releasing.wait(5)
    second.start()
    try:decision=progress.get(timeout=5)
    finally:
        proceed.set()
        first.join(5);second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert decision=='waiting-for-lease'
    assert len(errors)==1 and 'lease changed' in str(errors[0])
    assert target.list()['tasks']==[]
    with pytest.raises(WorktreeNotClaimed):registry.get(identity.worktree_id)
