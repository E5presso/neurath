# Result evaluation, optional reflection, and lessons

[한국어](../ko/result-evaluation.md) · [Phase runner](workflow-runner.md) · [Acceptance](acceptance.md)

#138 connects evaluation phases owned by `WorkflowRun`, actual independent reports owned by `Delegation`, and external waits and success reporting owned by `Task`. It adds no evaluation task, approval ledger, or token. This page describes the current internal APIs and isolated validation boundary. Shipping default skills and integrating business CLI commands remain in #149 and #148.

## Execution and report consumption

Set `PhaseDefinition.evaluation` to an `EvaluationTarget`. `RESULT` evaluates the user outcome and cannot have a skip condition. `REFLECTION` is an optional branch activated only by a user request. The target consists of the existing `target_revision`, related `task_ids`, and actual `artifacts` and `verification` references. The linked task is always in scope.

1. `GetEvaluationUseCase` reads conditions, scope, and the current candidate. It includes original sources and corrections, the session's complete TODO, and actual artifact and verification references. The TODO preserves successful, failed, and unfinished states.
2. `RequestEvaluationUseCase` checks phase order, reflection choice, and supported models and policies. It uses the existing `PrepareDelegationUseCase`, commits the phase attempt and external wait through `BindEvaluationUseCase`, then uses the existing peer, native child, or provider route. External execution holds no database write lock.
3. Peers and children submit their original reports through the existing acceptance and reporting path. Providers require actual completion, native session identity, output, and an execution reference. Request, delivery, failure, and unknown outcome are not successful reports.
4. `ConsumeEvaluationUseCase` compares the saved actual report against the current candidate. The executor records acceptance or rejection with original-source and verification evidence. Incorrect findings can be rejected with evidence; suggestions do not become new user instructions.
5. Confirmed shortfalls are handled in the same task list, through existing work or follow-up work using the original source. The existing workflow revision path reopens relevant implementation phases and evaluates changed results. `ReportResultUseCase` rejects success until evaluation succeeds. The evaluator does not complete the task directly.

The same candidate reuses its saved assignment and report. Reading a waiting or failed evaluation does not create another model execution. Evaluation assignments cannot recursively delegate another evaluation. A waiting attempt whose candidate changed is retained as failed history before a new candidate is attached; its original assignment and late report remain available. User cancellation and requirement corrections use the existing collaboration cancellation boundaries.

## Comparing related changes

`SQLAlchemyEvaluationContextService` fingerprints related task definitions, original source identities, the declared target, artifacts, and verification evidence. It gives the evaluator the complete TODO without including unrelated task status changes or evaluation records themselves in the fingerprint.

`GitEvaluationArtifactService` reads the actual content hashes of selected local files. Relative paths use the phase working directory; absolute `file:` paths are supported. Include `git:HEAD` explicitly when the current HEAD is relevant, such as a PR review. Unselected HEAD and file changes do not invalidate evaluation. For external references such as `artifact:...`, callers must supply an immutable revision reference identifying the current artifact. The service does not automatically download external URLs or grant publication rights.

The candidate is checked again when consuming a report and before final task success. Changes to local artifacts, selected HEAD, or related requirements therefore prevent completion using an old evaluation. Reading and accepting a report internally is separate from publication authority; host tools publish only within the user's authorized scope.

## Stop and reflection choices

Stop deterministically checks the existing latest task ledger. Evaluation waiting is an external wait on that `Task`; it returns control without being considered normal success. No model call or separate completion vote is added to Stop. New unfinished TODOs, failed or waiting tasks, old turns, and actual cancellation retain the existing runtime contract.

`ChooseReflectionUseCase` stores offered, requested, declined, or unanswered choices and their actual utterance or problem context on `WorkflowRun`. A problem is offered once, and an existing request is not reconfirmed. Unrequested, merely offered, declined, and unanswered reflection phases do not block original task completion. Only a request or ordinary acceptance activates the same independent evaluation path. There is no user-facing approval object or special token.

## Lesson lifecycle

`CreateLessonUseCase` creates a sourced `MemoryKind.LESSON` only after a successful current reflection evaluation requested by the user. `ObserveLessonUseCase` can add observations from later sessions in the same project.

- `PROPOSED` preserves the improvement candidate and scope without applying it.
- `VALIDATED` requires evidence for both the original failure case and a normal control.
- `APPLIED` records actual application after validation, distinguishing unknown, successful, and failed effects.
- `DEFERRED` preserves the reason and unapplied state without promoting deferral to success.
- `WITHDRAWN` connects later failure or regression to withdrawal of that lesson without overwriting past effects.

Existing `memory search/read` returns the original content and ordered lesson history. Application observations record evidence of changes and checks actually performed by the host; saving an observation does not itself modify user rules, goals, authority, or files.

## Preservation and validation boundary

`core_0013` retains existing assignments with an empty candidate and adds candidate-specific uniqueness, phase assignment links, reflection choices, and lesson history. It preserves existing source, task, assignment, and report IDs and foreign keys. Downgrades that would lose new evaluation, reflection, or lesson records are rejected.

`tests/test_evaluation.py` and `tests/test_evaluation_domain.py` run in the shared pre-commit and CI checks. They cover original-source and TODO delivery, actual subprocess fixture output, current candidate consumption, duplicate prevention, remediation, incorrect findings, related changes, optional reflection, lesson validation and withdrawal, deterministic Stop, and real migration boundaries. Existing runtime, collaboration, and provider tests retain coverage of cancellation, unknown outcomes, resumption, delivery, and storage failures.

Isolated subprocess and protocol fixtures do not prove actual model judgment or operational host activation. This change does not modify the user's installation or operational database; installed model catalog discovery is distinguished from executing a model evaluation.

If execution stops after the assignment and phase commit but before delivery, the same request continues the first delivery. Already delivered or execution-requested assignments are not submitted again. Lesson effects use standard optimistic revisions to prevent stale concurrent writes from losing history. Changes to the evaluation purpose or check conditions also change the related candidate.
