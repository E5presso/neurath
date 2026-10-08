"""Prepare configured checks; evidence comes only from matched host result metadata."""

import json
import shlex
from pathlib import Path
from uuid import uuid4

from neurath.application.catalog import validate
from neurath.domain.errors import AuthorizationError, ConflictError, ValidationError
from neurath.domain.models import Execution
from neurath.transport.runtime import application, database

SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'task_id': {'type': 'string', 'minLength': 1}, 'check_name': {'type': 'string', 'minLength': 1},
                         'criterion_id': {'type': 'string', 'minLength': 1}, 'phase_id': {'type': 'string', 'minLength': 1}},
          'required': ['task_id', 'check_name']}
TOOL = {'name': 'verification.prepare', 'description': 'Prepare a configured check. Run the returned native action once; the native-authorized runner records the actual child exit code. Read evidence.list afterward.', 'inputSchema': SCHEMA}


def prepare(root, actor, arguments):
    validate(SCHEMA, arguments)
    path = Path(root) / '.neurath/project.json'
    config = json.loads(path.read_text())
    check = config.get('verification', {}).get(arguments['check_name'])
    if not isinstance(check, dict):
        raise ValidationError('Unknown configured check')
    argv, codes = check.get('argv'), check.get('success_codes', [0])
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise ValidationError('Configured check argv is invalid')
    if not isinstance(codes, list) or not codes or not all(type(x) is int for x in codes):
        raise ValidationError('Configured check success codes are invalid')
    cwd = (Path(root) / check.get('cwd', '.')).resolve()
    if not cwd.is_relative_to(Path(root).resolve()):
        raise ValidationError('Configured check must run within this checkout')
    with database(root).uow() as uow:
        task = uow.repo('task').get(arguments['task_id'])
        if task is None or task.owner_id != actor or task.status != 'active':
            raise AuthorizationError('An active owned task is required')
        if arguments.get('criterion_id') and arguments['criterion_id'] not in {c.id for c in task.criteria}:
            raise ValidationError('Unknown criterion')
        if arguments.get('phase_id'):
            task.phase(arguments['phase_id'])
        record = Execution(id='execution_' + uuid4().hex, actor_id=actor, task_id=task.id, scope_version=task.scope_version,
                           argv=argv, cwd=str(cwd), expected_codes=codes, criterion_id=arguments.get('criterion_id'), phase_id=arguments.get('phase_id'))
        # Concurrent prepared copies of the same command would have ambiguous attribution.
        if any(r.status in {'prepared', 'running', 'executing'} and r.argv == argv and r.cwd == str(cwd) for r in uow.repo('execution').list(actor_id=actor)):
            raise ConflictError('This actor already has the same check prepared or running')
        uow.repo('execution').add(record)
        uow.commit()
    return {'execution_id': record.id, 'native_action': {'tool': 'exec_command', 'arguments': {'cmd': shlex.join([str(Path(root).resolve() / '.neurath/run'), 'check-run', record.id]), 'workdir': str(Path(root).resolve())}}, 'state': 'prepared'}


def observe_start(root, actor, payload):
    if payload.get('tool_name') not in {'exec_command', 'Bash', 'shell', 'shell_command'}:
        return
    values = payload.get('tool_input', {})
    command = values.get('cmd', values.get('command'))
    cwd = values.get('workdir', values.get('cwd', payload.get('cwd', str(root))))
    if not isinstance(command, str):
        return
    try:
        argv = shlex.split(command)
    except ValueError:
        return
    tool_id = payload.get('tool_use_id')
    if not isinstance(tool_id, str) or not tool_id:
        return
    with database(root).uow() as uow:
        matches = [r for r in uow.repo('execution').list(actor_id=actor) if r.status == 'prepared' and [str(Path(root).resolve() / '.neurath/run'), 'check-run', r.id] == argv and str(Path(root).resolve()) == str(Path(cwd).resolve())]
        if len(matches) > 1:
            raise ConflictError('Ambiguous prepared check')
        if matches:
            record = matches[0]
            task = uow.repo('task').get(record.task_id)
            if task.scope_version != record.scope_version or task.status != 'active':
                raise ConflictError('Prepared check task scope changed')
            previous = record.revision
            record.status, record.tool_use_id = 'running', tool_id
            record.changed()
            uow.repo('execution').save(record, previous)
        uow.commit()


def observe_finish(root, actor, payload, *, failed=False):
    tool_id = payload.get('tool_use_id')
    if not isinstance(tool_id, str):
        return
    store = database(root)
    with store.uow() as uow:
        records = [r for r in uow.repo('execution').list(actor_id=actor) if r.status == 'running' and r.tool_use_id == tool_id]
    if not records:
        return
    response = payload.get('tool_response')
    # Never parse stdout or JSON-looking output as a process exit attestation.
    code = response.get('exit_code') if isinstance(response, dict) else None
    if type(code) is not int:
        code = None
    if isinstance(response, dict) and response.get('session_id') is not None and code is None and not failed:
        return  # Native process is still running; no fabricated completion.
    for record in records:
        with store.uow() as uow:
            task = uow.repo('task').get(record.task_id)
            current_scope = task.scope_version == record.scope_version
        evidence = application(root).register_evidence(
            session_id=actor, event_id='check:' + record.id, task_id=record.task_id, evidence_type='tool',
            content=json.dumps({'execution_id': record.id, 'argv': record.argv, 'cwd': record.cwd, 'exit_code': code, 'host_failure': failed, 'scope_current': current_scope}, sort_keys=True),
            criterion_id=record.criterion_id, phase_id=record.phase_id, scope_version=record.scope_version,
            success=not failed and current_scope and code is not None and code in record.expected_codes,
        )
        with store.uow() as uow:
            current = uow.repo('execution').get(record.id)
            previous = current.revision
            current.status, current.exit_code, current.evidence_id = 'finished', code, evidence['id']
            current.changed()
            uow.repo('execution').save(current, previous)
            uow.commit()
