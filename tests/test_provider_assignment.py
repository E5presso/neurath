"""Recipients inspect the existing owned provider request without a second message/task."""
from dataclasses import asdict
import hashlib
import pytest

from neurath.agents.store import AgentIdentity,MessageStore
from neurath.providers import jobs
from neurath.providers.contracts import Session
from neurath.providers.report_routing import assignment_for,RECOVERY_ASSIGNMENT

pytest_plugins=['tests.test_agent_hooks']


@pytest.mark.parametrize('provider,native,issuer_host,issuer_session',[
    ('claude-code','ui','codex','api'),('codex','api','claude-code','ui')])
def test_owned_assignment_is_readable_before_dispatch(sessions,monkeypatch,provider,native,issuer_host,issuer_session):
    root,_=sessions
    owner=AgentIdentity(issuer_host,issuer_session,issuer_host+':session:'+issuer_session)
    receiver=AgentIdentity(provider,native,provider+':session:'+native)
    created=Session(provider,'claude-agent-sdk' if provider=='claude-code' else 'codex-app-server',
        native,str(root),None,'observed-model',{'requested':{'mode':'read-only'}})
    monkeypatch.setattr(jobs,'validate_target',lambda *a:root)
    monkeypatch.setattr(jobs,'_launch',lambda *a,**k:None)
    def execute(*a,event_callback,**fields):
        event_callback('native-created',{'created':asdict(created)})
        assert assignment_for(root,receiver) is None
        event_callback('assignment-ready',{'created':asdict(created),
            'assignment_digest':hashlib.sha256(fields['assignment'].encode()).hexdigest()})
        observed=assignment_for(root,receiver)
        assert observed['authority']=='peer-request'
        assert observed['issuer']==owner.address and observed['recipient']==receiver.address
        assert observed['assignment']=='Verify the assigned work'
        assert observed['purpose']=='assigned-work' and observed['worker_generation']==1
        assert assignment_for(root,owner) is None
        forged=AgentIdentity(provider,native,'another-actor')
        assert assignment_for(root,forged) is None
        assert MessageStore(root).inbox(receiver.address)==[]
        from tests.test_workflow_tasks import call
        status=call(sessions,'session_status',{},invocation='assignment-readback',
            host=provider,session=native)
        assert status['provider_assignment']==observed
        event_callback('started',{'native_session':native})
        return {'status':'completed','created':asdict(created),'text':'Done'}
    monkeypatch.setattr(jobs,'execute_session',execute)
    started=jobs.start(root,owner,{'provider':provider,'worktree':str(root),
        'assignment':'Verify the assigned work','mode':'read-only'},key='job')
    jobs.worker(root,started['run_id'])


def test_recovery_projection_does_not_replay_original_assignment(sessions,monkeypatch):
    from tests.test_provider_reply_route import run_report
    from neurath.providers.job_recovery import JobRecovery,ClosedTransportEvidence
    root,invoke=sessions
    store,owner,_,run_id=run_report(sessions,monkeypatch)
    prior=jobs.status(root,owner,run_id)['result']
    admitted=JobRecovery(store).recover(owner.address,run_id,'recover',ClosedTransportEvidence(
        generation=prior['worker_generation'],issuer_active=True,**prior['closure']))
    assert invoke('claude-code','ui','SessionStart',source='resume')[0]==0
    assert invoke('claude-code','ui','UserPromptSubmit',prompt='Recover inbox',turn_id='recovered-turn')[0]==0
    receiver=AgentIdentity('claude-code','ui','claude-code:session:ui')
    def execute(*a,event_callback,**fields):
        created=asdict(fields['restored_session'])
        event_callback('native-created',{'created':created})
        assert assignment_for(root,receiver) is None
        event_callback('assignment-ready',{'created':created,
            'assignment_digest':hashlib.sha256(fields['assignment'].encode()).hexdigest()})
        projection=assignment_for(root,receiver)
        assert projection['purpose']=='inbox-recovery'
        assert projection['assignment']==RECOVERY_ASSIGNMENT
        assert projection['original_assignment_digest']==hashlib.sha256(b'Observe').hexdigest()
        return {'status':'completed','created':created,'text':'Recovered'}
    monkeypatch.setattr(jobs,'execute_session',execute)
    jobs.worker(root,run_id,admitted['admission']['generation'])
