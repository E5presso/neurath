import json
import subprocess
from pathlib import Path
import pytest

from neurath.memory.migration_transcript import inspect_transcript

@pytest.fixture
def logs(tmp_path,monkeypatch):
    root=tmp_path/'project'
    subprocess.run(['git','init','-q',str(root)],check=True)
    native=tmp_path/'native'
    native.mkdir()
    monkeypatch.setattr('neurath.hosts.identity.host_storage',lambda *a:native)
    return root,native/'source.jsonl'

def write(path,events):
    path.write_text(''.join(json.dumps(e)+'\n' for e in events))

def test_codex_exact_source_recovers_native_failure_without_reasoning(logs):
    root,path=logs
    write(path,[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'turn_context','payload':{'turn_id':'turn'}},
        {'type':'response_item','payload':{'type':'reasoning','summary':[{'text':'private reasoning'}]}},
        {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Keep working'}]}},
        {'type':'event_msg','payload':{'type':'item_completed','thread_id':'source','turn_id':'turn','item':{
            'type':'CommandExecution','id':'exec','status':'failed','cwd':str(root),'exit_code':1,
            'command':['false'],'aggregated_output':'{"exit_code":0,"status":"passed"}'}}},
        {'type':'event_msg','payload':{'type':'task_complete','turn_id':'turn'}}])
    result=inspect_transcript(path,'codex','source',root)
    assert result['turn_closed'] and not result['pending_tools']
    assert 'private reasoning' not in json.dumps(result)
    assert result['entries'][-1]['exit_code']==1
    with pytest.raises(ValueError,match='metadata differs'):
        inspect_transcript(path,'codex','other',root)

def test_full_scan_keeps_call_before_old_tail_limit_and_detects_partial_line(logs):
    root,path=logs
    write(path,[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'response_item','payload':{'type':'custom_tool_call','call_id':'first','name':'exec'}},
        {'type':'response_item','payload':{'type':'reasoning','summary':'x'*(2*1024*1024+10)}},
        {'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'first','output':'result'}}])
    assert inspect_transcript(path,'codex','source',root)['pending_tools']==[]
    with path.open('a') as stream:stream.write('{"type":')
    assert inspect_transcript(path,'codex','source',root)['status']=='partial'

def test_claude_excludes_other_session_sidechain_and_thinking(logs):
    root,path=logs
    def e(kind,content,**extra):
        return {'type':kind,'sessionId':'source','cwd':str(root),'message':{'content':content},**extra}
    write(path,[e('user',[{'type':'text','text':'Original request'}]),
        e('assistant',[{'type':'thinking','thinking':'private'},{'type':'tool_use','id':'call','name':'Bash'}]),
        e('user',[{'type':'tool_result','tool_use_id':'call','is_error':False,'content':'done'}]),
        e('assistant',[{'type':'text','text':'other'}],sessionId='other'),
        e('assistant',[{'type':'text','text':'sidechain'}],isSidechain=True),
        {'type':'system','sessionId':'source','cwd':str(root),'subtype':'turn_duration'}])
    result=inspect_transcript(path,'claude-code','source',root)
    assert result['turn_closed'] and result['pending_tools']==[]
    assert all(x not in json.dumps(result['entries']) for x in ('private','sidechain','other'))

def test_wrong_project_and_symlink_are_rejected(logs,tmp_path):
    root,path=logs
    other=tmp_path/'other'
    subprocess.run(['git','init','-q',str(other)],check=True)
    write(path,[{'type':'session_meta','payload':{'id':'source','cwd':str(other)}}])
    with pytest.raises(ValueError,match='Git project'):
        inspect_transcript(path,'codex','source',root)
    link=path.parent/'link.jsonl'
    link.symlink_to(path)
    with pytest.raises(ValueError,match='host storage'):
        inspect_transcript(link,'codex','source',root)

@pytest.mark.parametrize('host',['codex','claude-code'])
def test_completed_tool_context_is_recovered_without_inventing_success(logs,host):
    root,path=logs
    if host=='codex':
        events=[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
            {'type':'response_item','payload':{'type':'function_call','name':'exec_command','call_id':'call','arguments':'{"cmd":"false"}'}},
            {'type':'response_item','payload':{'type':'function_call_output','call_id':'call','output':'failure details'}}]
    else:
        events=[{'type':'assistant','sessionId':'source','cwd':str(root),'message':{'content':[
            {'type':'tool_use','name':'Bash','id':'call','input':{'command':'false'}}]}},
            {'type':'user','sessionId':'source','cwd':str(root),'message':{'content':[
            {'type':'tool_result','tool_use_id':'call','content':'failure details','is_error':True}]}}]
    write(path,events)
    result=inspect_transcript(path,host,'source',root)
    assert result['pending_tools']==[]
    assert result['entries'][0]['kind']=='tool'
    assert result['entries'][0]['authority']=='reference-only'
    assert 'false' in json.dumps(result['entries'])
    assert 'failure details' in json.dumps(result['entries'])

def test_background_claude_tool_stays_unsettled(logs):
    root,path=logs
    write(path,[{'type':'assistant','sessionId':'source','cwd':str(root),'message':{'content':[
        {'type':'tool_use','name':'Bash','id':'call','input':{'command':'sleep 60','run_in_background':True}}]}},
        {'type':'user','sessionId':'source','cwd':str(root),'toolUseResult':{'backgroundTaskId':'job'},
         'message':{'content':[{'type':'tool_result','tool_use_id':'call','is_error':False,'content':'started'}]}}])
    assert inspect_transcript(path,'claude-code','source',root)['pending_tools']==['background:call']

def test_pull_uses_source_registered_storage_not_receivers_environment(logs,tmp_path,monkeypatch):
    from neurath.memory.migration import observe_source
    root,path=logs
    write(path,[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'turn_context','payload':{'turn_id':'turn'}},
        {'type':'event_msg','payload':{'type':'turn_aborted','turn_id':'turn'}}])
    monkeypatch.setattr('neurath.hosts.identity.host_storage',lambda *a:tmp_path/'different-receiver-home')
    monkeypatch.setattr('neurath.hosts.identity.snapshot',lambda *a:{
        'host':'codex','session':'source','transcript':str(path),'connected':False})
    result=observe_source(root,'codex','source')
    assert result['quiescent']
    assert result['transcript']['fingerprint']['path']==str(path)
    # The parser alone must still reject unregistered paths outside host storage.
    with pytest.raises(ValueError,match='host storage'):
        inspect_transcript(path,'codex','source',root)

def test_codex_background_process_requires_matching_observed_exit(logs):
    root,path=logs
    events=[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'turn_context','payload':{'turn_id':'turn'}},
        {'type':'response_item','payload':{'type':'function_call','name':'exec_command','call_id':'exec','arguments':'{"cmd":"sleep 60"}'}},
        {'type':'response_item','payload':{'type':'function_call_output','call_id':'exec',
            'output':json.dumps({'session_id':123,'output':'','exit_code':None})}},
        {'type':'event_msg','payload':{'type':'turn_aborted','turn_id':'turn'}}]
    write(path,events)
    assert inspect_transcript(path,'codex','source',root)['pending_tools']==['process:123']
    events.extend([
        {'type':'response_item','payload':{'type':'function_call','name':'write_stdin','call_id':'wait','arguments':'{"session_id":123}'}},
        {'type':'response_item','payload':{'type':'function_call_output','call_id':'wait',
            'output':json.dumps({'output':'finished','exit_code':0})}}])
    write(path,events)
    assert inspect_transcript(path,'codex','source',root)['pending_tools']==[]

def test_codex_native_started_command_is_unsettled_until_completed(logs):
    root,path=logs
    events=[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'event_msg','payload':{'type':'item_started','thread_id':'source','item':{
            'type':'CommandExecution','id':'running','cwd':str(root)}}}]
    write(path,events)
    assert inspect_transcript(path,'codex','source',root)['pending_tools']==['running']
    events.append({'type':'event_msg','payload':{'type':'item_completed','thread_id':'source','item':{
        'type':'CommandExecution','id':'running','cwd':str(root),'status':'completed','exit_code':0}}})
    write(path,events)
    assert inspect_transcript(path,'codex','source',root)['pending_tools']==[]

def test_pull_finds_exact_archived_codex_transcript(logs,tmp_path,monkeypatch):
    from neurath.memory.migration import observe_source
    root,_=logs
    native=tmp_path/'custom-codex'
    original=native/'sessions/2026/09/13/rollout-source.jsonl'
    archived=native/'archived_sessions'/original.name
    archived.parent.mkdir(parents=True)
    write(archived,[{'type':'session_meta','payload':{'id':'source','cwd':str(root)}},
        {'type':'turn_context','payload':{'turn_id':'turn'}},
        {'type':'event_msg','payload':{'type':'turn_aborted','turn_id':'turn'}}])
    monkeypatch.setattr('neurath.hosts.identity.snapshot',lambda *a:{
        'host':'codex','session':'source','transcript':str(original),'connected':False})
    result=observe_source(root,'codex','source')
    assert result['quiescent']
    assert result['transcript']['fingerprint']['path']==str(archived)
    write(archived,[{'type':'session_meta','payload':{'id':'foreign','cwd':str(root)}}])
    with pytest.raises(ValueError,match='metadata differs'):observe_source(root,'codex','source')
