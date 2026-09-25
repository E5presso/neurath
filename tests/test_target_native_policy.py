"""Explicit target-native launches preserve the target profile, not source settings."""
import json
import pytest

from neurath.agents.store import AgentIdentity
from neurath.runtime.provider_policy import resolve_policy

pytest_plugins = ["tests.test_mcp_policy_inheritance"]

def test_claude_target_native_preserves_own_mode_and_hooks(roots):
    source, target = roots
    for root in (source, target):
        (root / '.claude').mkdir()
    (target / '.claude/settings.json').write_text(json.dumps({
        'permissions': {'defaultMode': 'auto', 'deny': ['Bash(forbidden *)']},
        'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'target-hook'}]}]}}))
    before = (target / '.claude/settings.json').read_bytes()
    result = resolve_policy(source, AgentIdentity('codex', 'source', 'owner'),
        {'provider': 'claude-code', 'worktree': str(target), 'mode': 'target-native'},
        {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'}})
    assert result['permission_mode'] == 'auto'
    assert result['mode'] == 'native'
    assert result['policy_inheritance']['strategy'] == 'target-native'
    assert result['policy_inheritance']['controls']['tool_denylist'] == ['Bash(forbidden *)']
    assert result['policy_inheritance']['controls']['hooks']
    assert (target / '.claude/settings.json').read_bytes() == before

def test_target_native_does_not_accept_a_conflicting_mode_override(roots):
    source, target = roots
    (target / '.claude').mkdir()
    (target / '.claude/settings.json').write_text('{"permissions":{"defaultMode":"auto"}}')
    with pytest.raises(ValueError, match='target-native.*permission_mode'):
        resolve_policy(source, AgentIdentity('codex', 'source', 'owner'),
            {'provider':'claude-code','worktree':str(target),'mode':'target-native',
             'permission_mode':'bypassPermissions'},
            {'approval_policy':'never','sandbox_policy':{'type':'danger-full-access'}})

def test_target_native_requires_an_observed_claude_default(roots):
    source, target = roots
    with pytest.raises(ValueError, match='target-native.*defaultMode'):
        resolve_policy(source, AgentIdentity('codex','source','owner'),
            {'provider':'claude-code','worktree':str(target),'mode':'target-native'},
            {'approval_policy':'never','sandbox_policy':{'type':'danger-full-access'}})

def test_target_native_schema_is_explicit_and_inherit_is_unchanged():
    from neurath.runtime.task_schema import arguments
    assert arguments('provider_run',{'worktree':'/fixture','assignment':'Check','mode':'target-native'})['mode']=='target-native'
    assert arguments('provider_run',{'worktree':'/fixture','assignment':'Check'})['mode']=='inherit'


def test_codex_target_defaults_preserve_workspace_dimensions(monkeypatch, tmp_path):
    from neurath.runtime.provider_policy import target_native_settings
    class Host:
        def __init__(self, root, **kwargs):
            assert root == tmp_path
        def request(self, method, arguments):
            assert method == 'config/read'
            return {'config': {'approval_policy':'never', 'sandbox_mode':'workspace-write',
                'sandbox_workspace_write': {'network_access':True,
                    'writable_roots':[str(tmp_path/'extra')], 'exclude_slash_tmp':True}}}
        def close(self):
            pass
    monkeypatch.setattr('neurath.providers.stdio.CodexStdio', Host)
    result = target_native_settings(tmp_path, 'codex')
    assert result['sandbox_policy'] == {'type':'workspace-write','network_access':True,
        'writable_roots':[str(tmp_path/'extra')], 'exclude_slash_tmp':True}

def test_claude_auto_allows_only_controlled_provider_operation_delegation(monkeypatch):
    from neurath.runtime.tasks import _mcp_execution_policy
    from neurath.runtime.task_schema import TaskError
    report={'implementation_ready':True,'stages':{name:{'status':'verified','evidence':{}}
        for name in ('installation','activation','ownership','policy')}}
    report['stages']['policy']['evidence']={'permission_mode':'auto'}
    monkeypatch.setattr('neurath.providers.readiness.inspect_bound_readiness',lambda *a,**k:report)
    monkeypatch.setattr('neurath.runtime.provider_policy.controls',lambda *a,**k:{
        'filesystem':'unobserved','network':'unobserved','tool_denylist':[]})
    caller=AgentIdentity('claude-code','source','owner')
    with pytest.raises(TaskError,match='execution policy'):
        _mcp_execution_policy(None,caller,'turn')
    assert _mcp_execution_policy(None,caller,'turn',controlled_provider_operation=True)==report
    report['stages']['policy']['evidence']['permission_mode']='plan'
    with pytest.raises(TaskError,match='execution policy'):
        _mcp_execution_policy(None,caller,'turn',controlled_provider_operation=True)

@pytest.mark.parametrize('source_host,target_host',[('claude-code','codex'),('codex','claude-code')])
def test_fresh_native_owner_can_observe_plan_and_admit_target_native(roots,monkeypatch,source_host,target_host):
    import subprocess
    from neurath.runtime import model_tasks, provider_execution
    from neurath.providers.model_planning import Inventory, ModelInfo
    from neurath.runtime.task_schema import arguments
    source,target=roots
    target=source
    subprocess.run(['git','init','-q',str(source)],check=True)
    caller=AgentIdentity(source_host,'source','owner')
    report={'implementation_ready':True,'stages':{name:{'status':'verified','evidence':{}}
        for name in ('installation','activation','ownership','policy')}}
    report['stages']['policy']['evidence']=({'permission_mode':'auto'} if source_host=='claude-code' else {
        'approval_policy':'never','approvals_reviewer':'user','sandbox_policy':{'type':'danger-full-access'}})
    monkeypatch.setattr('neurath.providers.readiness.inspect_bound_readiness',lambda *a,**k:report)
    monkeypatch.setattr('neurath.runtime.tasks._verification_owner',lambda *a:(1,'turn'))
    monkeypatch.setattr('neurath.runtime.provider_policy.target_native_settings',lambda *a:
        {'permission_mode':'auto'} if target_host=='claude-code' else {
        'approval_policy':'never','collaboration_mode':'default','sandbox_policy':{'type':'danger-full-access'}})
    observations=[]
    def refresh(*a,**k):
        observations.append('refresh')
        return Inventory(target_host,'local','native:model/list','revision',models=(ModelInfo('exact'),))
    monkeypatch.setattr(model_tasks,'refresh_inventory',refresh)
    inventory=model_tasks.run(source,'provider_models',{'provider':target_host,'worktree':str(target)},
        identity=caller,expected_turn='turn')
    fields={'provider':target_host,'worktree':str(target),'assignment':'Continue work',
        'inventory_id':inventory['inventory_id'],'execution':{'mode':'target-native'},
        'selection':{'model':'exact'},'difficulty':'routine','evidence':['Bounded change'],
        'confidence':'high','rationale':'Sufficient for this task','rejected_alternatives':[],
        'replan_triggers':['scope changes'],'key':'plan'}
    plan=model_tasks.run(source,'provider_plan',arguments('provider_plan',fields),identity=caller,expected_turn='turn')
    launched=[]
    def start(root,identity,fields,**kwargs):
        launched.append(fields)
        return {'status':'accepted'}
    monkeypatch.setattr('neurath.providers.jobs.start',start)
    result=provider_execution.run(source,{'provider':target_host,'worktree':str(target),
        'purpose':'perspective','reason':'Independent alternative from the other provider',
        'assignment':'Continue work','mode':'target-native','model':'exact','plan_id':plan['plan_id'],
        'plan_revision':plan['revision'],'key':'run'},identity=caller,expected_turn='turn')
    assert result['status']=='accepted' and len(launched)==1
    assert launched[0]['policy_inheritance']['strategy']=='target-native'
    assert observations==['refresh']
