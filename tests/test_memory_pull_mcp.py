"""Both native caller bindings reach the receiver-owned pull service."""
import json
import pytest

pytest_plugins = ["tests.test_agent_hooks"]

@pytest.mark.parametrize('source_host,source_session,target_host,target_session',[
    ('codex','api','claude-code','ui'),('claude-code','ui','codex','api')])
def test_native_bound_pull_without_source_checkpoint(sessions,source_host,source_session,target_host,target_session):
    from tests.test_workflow_tasks import call
    from tests.test_task_ledger_service import item
    root,invoke=sessions
    claim=call(sessions,'worktree_claim',{},host=source_host,session=source_session)
    original=call(sessions,'task_define',{'tasks':[item('unfinished')],
        'expected_revision':0,'key':'source-intake'},host=source_host,session=source_session)
    transcript=root/'host-storage'/f'{source_session}.jsonl'
    if source_host=='codex':
        events=[{'type':'session_meta','payload':{'id':source_session,'cwd':str(root)}},
                {'type':'turn_context','payload':{'turn_id':source_session+'-turn'}},
                {'type':'event_msg','payload':{'type':'task_complete','turn_id':source_session+'-turn'}}]
    else:
        events=[{'type':'user','sessionId':source_session,'cwd':str(root),'message':{
            'content':[{'type':'text','text':'Finish the interrupted work'}]}},
            {'type':'system','sessionId':source_session,'cwd':str(root),'subtype':'turn_duration'}]
    transcript.write_text(''.join(json.dumps(e)+'\n' for e in events))
    assert invoke(source_host,source_session,'SessionEnd')[0]==0
    preview=call(sessions,'memory_pull',{'action':'preview','source_host':source_host,
        'source_session':source_session,'key':'receiver-preview'},host=target_host,session=target_session)
    assert preview['source']['session']==source_session
    adopted=call(sessions,'memory_pull',{'action':'adopt','reference':preview['reference'],
        'expected_revision':0,'key':'receiver-adopt'},invocation='adopt',host=target_host,session=target_session)
    assert adopted['status']=='adopted'
    assert adopted['claim']['actor_id']!=claim['actor_id']
    assert adopted['claim']['fencing_token']!=claim['fencing_token']
    assert original['tasks'][0]['id'] in adopted['task_mapping']
    current=call(sessions,'task_list',{},invocation='receiver-list',host=target_host,session=target_session)
    assert len(current['tasks'])==1 and current['tasks'][0]['status']=='pending'
    assert invoke(source_host,source_session,'SessionStart',source='resume')[0]==0
    if source_host=='codex':
        with transcript.open('a') as stream:
            stream.write(json.dumps({'type':'turn_context','payload':{'turn_id':source_session+'-resumed'}})+'\n')
    assert invoke(source_host,source_session,'UserPromptSubmit',prompt='Inspect the migration',
                  turn_id=source_session+'-resumed')[0]==0
    code,_,diagnostic=invoke(source_host,source_session,'PreToolUse',
        tool_name='mcp__neurath_collaboration__worktree_claim',tool_use_id='stale-server-call',tool_input={})
    assert code==2 and 'migrated' in diagnostic
