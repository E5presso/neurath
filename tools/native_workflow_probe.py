"""Live conformance driver. Every role binds ONLY from its actual host environment."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from neurath.runtime.engine import activate
ROOT=Path.cwd().resolve()
activate(ROOT)
from scripts.agent_harness import adaptive_control as ac
from scripts.agent_harness import session_kernel as sk
from scripts.agent_harness.adaptive_control_store import AdaptiveControlState, AdaptiveControlStore
from scripts.agent_harness.adaptive_control_authority import AdaptiveControlAuthorityVerifier
from scripts.agent_harness.adaptive_evaluation_candidate import AdaptiveEvaluationCandidateStore
from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle
from scripts.agent_harness.state_cli import StateCliApplication
from neurath.hosts.identity import prepare_delegation
binding=RuntimeEnvironmentResolver().resolve(os.environ)
handle=StateHandle.attach(sk.SessionLocator.from_worktree(ROOT),binding)
WF=sk.WorkflowId('live-validation')
DRAFT=sk.DelegationId('live-draft')
FINAL=sk.DelegationId('live-evaluator')
FILE=binding.runtime.value+'-repair-result.txt'
CONTENT=b'NEURATH_WORKFLOW_OK\n'
GOAL=f'Create {FILE} with exact bytes NEURATH_WORKFLOW_OK followed by newline; preserve README and pass check.sh.'
SOURCE='sha256:'+hashlib.sha256((ROOT/'README.md').read_bytes()).hexdigest()
CONSTRAINTS=('Only the disposable fixture may change.','An actual independent child must verify the result.')
NON_GOALS=('Publication and external integrations are out of scope.',)
REQ=ac.approved_requirement_fingerprint(GOAL,CONSTRAINTS,NON_GOALS,1,SOURCE)
contract=ac.GoalContract(goal=GOAL,constraints=CONSTRAINTS,criteria=(ac.CriterionSpec(criterion_id='fixture-complete',description='Exact output file, unchanged README and successful check.sh',source_requirement_id='REQ-live-fixture',approved_requirement_fingerprint=REQ,observer='native independent child',precondition='Parent has completed the native file write',stimulus='Read output file and README; run check.sh',expected_outcome='Output exact, source unchanged, script exit zero with marker',oracle_owner=ac.OracleOwner.INDEPENDENT_EVALUATOR,hard=True,required_evidence=frozenset({ac.EvidenceKind.INDEPENDENT_SEMANTIC})),),requirement_ids=frozenset({'REQ-live-fixture'}),non_goals=NON_GOALS,intent_revision=1,source_revision=SOURCE)
inventory=ac.GapInventory(intent_revision=1,source_revision=SOURCE,assessed_sections=frozenset(ac.RequirementSection),gaps=())
store=AdaptiveControlStore(SkillStateStore(handle,WF))

def emit(value): print(json.dumps(value,ensure_ascii=False),flush=True)
def cli(args, expect=0):
 result=StateCliApplication().run(args,os.environ,ROOT)
 if result.exit_code!=expect: raise RuntimeError(result.stdout)
 return json.loads(result.stdout)
def wait_for(predicate):
 until=time.monotonic()+120
 while time.monotonic()<until:
  found=predicate(handle.inspect())
  if found: return found
  time.sleep(.3)
 raise TimeoutError('real peer did not reach expected state')
def report(delegation,ref,summary):
 handle.apply(sk.DelegationReported(session_id=handle.session_id,delegation_id=delegation,reporter_actor_id=handle.actor_id,result=sk.DelegationResult(verdict='pass',summary=summary,outcome_ref=ref,blocking_findings=()),idempotency_key='live-report:'+str(delegation)))
def consume(delegation):
 handle.apply(sk.DelegationConsumed(session_id=handle.session_id,delegation_id=delegation,consumer_actor_id=handle.actor_id,idempotency_key='live-consume:'+str(delegation)))
def final_state(evaluator,ref):
 lineage=ac.AuthorityReceipt(authority=ac.EvidenceAuthority.INDEPENDENT_EVALUATOR,issuer_id=str(evaluator),subject_id=str(handle.actor_id),intent_revision=1,source_revision=SOURCE,receipt_digest=ref.removeprefix('sha256:'),delegation_id=str(FINAL))
 return AdaptiveControlState(contract=contract,inventory=inventory,evidence=(ac.CriterionEvidence(goal_fingerprint=contract.fingerprint,criterion_id='fixture-complete',kind=ac.EvidenceKind.INDEPENDENT_SEMANTIC,authority=ac.EvidenceAuthority.INDEPENDENT_EVALUATOR,status=ac.EvidenceStatus.PASS,reference='live:fixture-readback',lineage=lineage),),coverage=ac.GoalCoverage(goal_fingerprint=contract.fingerprint,criterion_ids=frozenset({'fixture-complete'}),authority=ac.EvidenceAuthority.INDEPENDENT_EVALUATOR,status=ac.EvidenceStatus.PASS,reference='live:fixture-coverage',goal_alignment=1.,semantic_drift=0.,uncertainty=0.,reward_hacking_risk=0.,lineage=lineage),execution_status=ac.ExecutionStatus.COMPLETED,observations=())
role=sys.argv[1]
if role=='init':
 assert binding.is_root
 cli(['worktree','claim'])
 handle.apply(sk.WorkflowStarted(session_id=handle.session_id,workflow_id=WF,owner_actor_id=handle.actor_id,kind='neurath-validation',goal=GOAL,payload={'skill_state':{}},idempotency_key='live-workflow-start'))
 initial=AdaptiveControlState.empty(contract,inventory)
 store.compare_and_replace_payload(handle.inspect().workflows[WF].revision,initial.to_payload())
 expected=hashlib.sha256(b'neurath.material-observable.v1\0regular\0' + b'0644\0'+CONTENT).hexdigest()
 cli(['action','prepare','--batch-id','live-write','--kind','local-mutation','--target',FILE,'--expectations-json',json.dumps([{'observable_id':FILE,'expected_delta':'created','expected_digest':expected}])])
 emit({'status':'prepared','file':FILE,'content':CONTENT.decode(),'session_id':str(handle.session_id)})
elif role=='prepare-review':
 assert binding.is_root
 batch=handle.inspect().material_actions[handle.actor_id]
 if batch.status.value == 'open':
  cli(['action','resolve','--batch-id','live-write','--expected-revision',str(batch.revision),'--resolution','completed'])
 else:
  assert batch.resolution.value == 'completed' and batch.invocations, 'resume must preserve the actual successful write receipt'
 trajectory=AdaptiveEvaluationCandidateStore(handle,WF).current_trajectory_digest()
 assignment=json.dumps({'kind':'live-draft-evaluation','workflow_id':str(WF),'goal':GOAL,'goal_fingerprint':contract.fingerprint,'trajectory_digest':trajectory,'source_revision':SOURCE,'final_delegation':str(FINAL)})
 emit(prepare_delegation(ROOT,str(DRAFT),assignment))
elif role=='child':
 assert not binding.is_root, 'native child must never run as root'
 draft=wait_for(lambda s:s.delegations.get(DRAFT))
 assert draft.target_actor_id==handle.actor_id
 assignment=json.loads(draft.assignment)
 assert assignment['goal']==GOAL and assignment['goal_fingerprint']==contract.fingerprint
 # Real repository ownership conflict must reject this child.
 denial=cli(['worktree','claim'],expect=2)
 assert (ROOT/FILE).read_bytes()==CONTENT
 assert 'sha256:'+hashlib.sha256((ROOT/'README.md').read_bytes()).hexdigest()==assignment['source_revision']
 check=subprocess.run(['/bin/sh','check.sh'],capture_output=True,text=True,check=True)
 assert 'NEURATH_PROJECT_CHECK_OK' in check.stdout
 claims=[{'authority':'independent-evaluator','claim_type':'criterion-evidence','evaluation_revision':1,'criterion_id':'fixture-complete','goal_fingerprint':contract.fingerprint,'kind':'independent-semantic','reference':'live:fixture-readback','status':'pass'}, {'authority':'independent-evaluator','claim_type':'goal-coverage','evaluation_revision':1,'criterion_ids':['fixture-complete'],'goal_alignment':1.,'goal_fingerprint':contract.fingerprint,'reference':'live:fixture-coverage','reward_hacking_risk':0.,'semantic_drift':0.,'status':'pass','uncertainty':0.}, {'authority':'independent-evaluator','claim_type':'execution-completion','goal_fingerprint':contract.fingerprint,'status':'completed'}]
 result={'blocking_findings':[],'claims':sorted(claims,key=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))),'goal_fingerprint':contract.fingerprint,'intent_revision':1,'kind':'adaptive-goal-evaluation','source_revision':SOURCE,'summary':'adaptive goal evaluation passed','verdict':'pass','workflow_id':str(WF),'trajectory_assessment':{'blocking_findings':[],'trajectory_digest':assignment['trajectory_digest'],'verdict':'pass'}}
 artifact=SessionArtifactStore(handle).put_json({'delegation_id':str(FINAL),'report':result,'schema':'neurath.delegation-result.v1','target_agent_id':str(handle.actor_id)})
 report(DRAFT,artifact.reference,'Actual fixture readback; awaiting exact candidate to review')
 emit({'status':'draft-reported','actor_id':str(handle.actor_id),'artifact':artifact.reference,'ownership_denied':denial})
 final=wait_for(lambda s:s.delegations.get(FINAL))
 candidate=AdaptiveEvaluationCandidateStore(handle,WF).read_candidate(final.assignment)
 a=json.loads(final.assignment)
 assert candidate.state.contract.fingerprint==contract.fingerprint
 assert candidate.state.coverage.lineage.receipt_digest==artifact.reference.removeprefix('sha256:')
 assert candidate.state.coverage.lineage.issuer_id==str(handle.actor_id)
 assert candidate.trajectory['material_action']['resolution']=='completed'
 assert a['trajectory_digest']==assignment['trajectory_digest']
 report(FINAL,artifact.reference,json.dumps({'candidate_ref':candidate.candidate_ref,'summary':'adaptive goal evaluation passed','trajectory_digest':a['trajectory_digest']},sort_keys=True,separators=(',',':')))
 emit({'status':'reported','actor_id':str(handle.actor_id),'candidate_ref':candidate.candidate_ref,'outcome_ref':artifact.reference})
elif role=='complete':
 assert binding.is_root
 draft=wait_for(lambda s:s.delegations.get(DRAFT) if s.delegations.get(DRAFT) and s.delegations[DRAFT].status is sk.DelegationStatus.REPORTED else None)
 evaluator=draft.target_actor_id;ref=draft.result.outcome_ref
 consume(DRAFT)
 candidate=final_state(evaluator,ref)
 revision=handle.inspect().workflows[WF].revision
 try:
  AdaptiveControlAuthorityVerifier(handle,WF).validate_candidate(candidate,revision)
 except Exception as error:
  emit({'premature_completion_rejected':type(error).__name__})
 else: raise AssertionError('completion without consumed final report was accepted')
 prepared=AdaptiveEvaluationCandidateStore(handle,WF).prepare(candidate)
 handle.apply(sk.DelegationAssigned(session_id=handle.session_id,delegation_id=FINAL,owner_actor_id=handle.actor_id,target_actor_id=evaluator,assignment=prepared.assignment_json,idempotency_key='live-final-assign',topology_policy=sk.DelegationTopologyPolicy.DIRECT_CHILD))
 wait_for(lambda s:s.delegations.get(FINAL) and s.delegations[FINAL].status is sk.DelegationStatus.REPORTED)
 consume(FINAL)
 revision=handle.inspect().workflows[WF].revision
 verifier=AdaptiveControlAuthorityVerifier(handle,WF)
 verifier.validate_candidate(candidate,revision)
 saved=store.compare_and_replace_payload(revision,candidate.to_payload())
 verified=verifier.verify_completion(saved.workflow_revision)
 assert verified.external_authority.complete
 current=handle.inspect().workflows[WF]
 handle.apply(sk.WorkflowFinalized(session_id=handle.session_id,workflow_id=WF,actor_id=handle.actor_id,expected_workflow_revision=current.revision,terminal_status=sk.WorkflowStatus.COMPLETED,payload=current.payload,idempotency_key='live-finalize'))
 cli(['worktree','release'])
 emit({'status':'completed','session_id':str(handle.session_id),'root_actor':str(handle.actor_id),'evaluator':str(evaluator),'workflow_status':handle.inspect().workflows[WF].status.value,'independent_authority':verified.external_authority.complete,'decision':verified.receipt.decision.action.value,'candidate_ref':prepared.candidate_ref,'outcome_ref':ref,'material_receipt':handle.inspect().material_actions[handle.actor_id].to_payload(),'delegation':handle.inspect().delegations[FINAL].to_payload()})
elif role=='abort':
 assert binding.is_root
 state=handle.inspect();workflow=state.workflows.get(WF)
 if workflow and workflow.status is sk.WorkflowStatus.ACTIVE:
  current=store.read()
  store.compare_and_replace_payload(workflow.revision,replace(current.state,execution_status=ac.ExecutionStatus.FAILED).to_payload())
  workflow=handle.inspect().workflows[WF]
  handle.apply(sk.WorkflowFinalized(session_id=handle.session_id,workflow_id=WF,actor_id=handle.actor_id,expected_workflow_revision=workflow.revision,terminal_status=sk.WorkflowStatus.FAILED,payload=workflow.payload,idempotency_key='live-abort'))
 batch=handle.inspect().material_actions.get(handle.actor_id)
 if batch and batch.status.value=='open' and not batch.in_flight:
  cli(['action','resolve','--batch-id',batch.batch_id,'--expected-revision',str(batch.revision),'--resolution','aborted'])
 released=StateCliApplication().run(['worktree','release'],os.environ,ROOT)
 emit({'status':'aborted','release':released.stdout})
else: raise ValueError(role)
