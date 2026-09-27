"""Exercise the installed Neurath wave guard through a real Codex code-mode host.

Use an already trusted project and an explicitly selected host executable.
The isolated test thread owns its tasks, children and stdin-waiting process.
"""
import argparse
import json
from pathlib import Path

from native_steering_probe import Host


def probe(project, output, executable, model):
    output.mkdir(parents=True, exist_ok=True)
    host = Host(project, output, executable)
    try:
        hooks = host.request('hooks/list', {'cwds': [str(project)]})
        (output / 'hooks.json').write_text(json.dumps(hooks, indent=2))
        configured = hooks['data'][0]['hooks']
        assert configured and all(h['trustStatus'] == 'trusted' and h['enabled'] for h in configured)
        thread = host.request('thread/start', {
            'cwd': str(project), 'model': model, 'approvalPolicy': 'never', 'sandbox': 'read-only',
            'config': {'features.code_mode': True, 'features.code_mode_host': True},
        })['thread']['id']
        prompt = (
            'Run an explicitly authorized read-only Neurath native wave regression, not product work. '
            'Use named task tools to define and start one task whose acceptance is: a real live '
            'exec session poll is rejected by Neurath while two wave slots are ready; a nonwaiting '
            'nested named tool works; both read-only children finish and their results are consumed. '
            'Verify the worktree is unclaimed, then acquire its native claim for this read-only '
            'fixture. The caller has released its own claim for this test. Do not force takeover. '
            'Do not edit files, change trust/settings, or start phase workflows. '
            'Before preparing the wave, start /bin/cat using exec_command with tty=true and '
            'yield_time_ms=250. Retain its actual live session_id. '
            'Prepare a two-entry max_parallel=2 wave with independent read-only children whose '
            'assignment is to inspect README and report one existing fact through artifact_put '
            'and evaluation_report. Before dispatching children, execute one intentional negative '
            'test: from functions.exec call tools.write_stdin with that actual session_id, '
            'chars="" and yield_time_ms=1000. Catch and record the real Neurath dispatch denial. '
            'Do not replace the process ID with an invalid one. Read the wave and retain its '
            'native last_wait_denial observation. Then call a nonwaiting nested '
            'session_status and confirm it succeeds while the slots remain ready. '
            'Execute the returned dispatch_prepare_code and direct native spawn for each ready '
            'entry, filling both slots before waiting. After both dispatches, send Ctrl-D to '
            'the cat session with write_stdin and observe its actual exit. '
            'Wait for the children, read their actual artifacts, consume reported successful '
            'results, and read the wave to verify all_succeeded. Resolve only this test task '
            'using the actual observations, display native TODO, release your exact observed '
            'claim, and finish NEURATH_WAVE_PROBE_OK. '
            'On a concrete failed prerequisite, clean up your owned cat process and report the '
            'exact failed test condition, release any claim you acquired, without inventing '
            'child reports or changing other work.'
        )
        turn = host.request('turn/start', {'threadId': thread,
            'input': [{'type': 'text', 'text': prompt}]})['turn']['id']
        print(json.dumps({'thread': thread, 'turn': turn, 'output': str(output)}), flush=True)
        end = host.wait(lambda e: e.get('method') == 'turn/completed'
            and e.get('params', {}).get('threadId') == thread, timeout=1200)
        (output / 'completion.json').write_text(json.dumps(end, indent=2))
        assert end['params']['turn']['status'] == 'completed', end
        report = verify_wave_events(host.events, thread, turn)
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        host.close()


def verify_wave_events(events, thread, turn):
    prepared = nonwaiting = succeeded = resolved = released = exited = None
    process = claim = wave_id = task_id = ready = observation = None
    first_dispatch = None
    blocks = {}
    for index, event in enumerate(events):
        params = event.get('params', {})
        if params.get('threadId') != thread or params.get('turnId') != turn:
            continue
        if event.get('method') == 'hook/completed':
            run = params.get('run', {})
            if (run.get('eventName') == 'preToolUse' and run.get('status') == 'blocked'
                    and 'dispatch ready wave work' in json.dumps(run.get('entries', []))):
                blocks[run['id'].rsplit(':', 1)[-1]] = index
        item = params.get('item', {})
        if item.get('type') == 'commandExecution' and any(
                action.get('command') == '/bin/cat' for action in item.get('commandActions', [])):
            if event.get('method') == 'item/started':
                assert process is None and item.get('status') == 'inProgress'
                assert item.get('processId') and item.get('exitCode') is None
                process = {'index': index, 'item_id': item['id'], 'id': int(item['processId'])}
            if event.get('method') == 'item/completed':
                assert process and item['id'] == process['item_id']
                assert int(item['processId']) == process['id'] and item.get('exitCode') == 0
                exited = index
        if event.get('method') != 'item/completed' or item.get('type') != 'mcpToolCall':
            continue
        result = (item.get('result') or {}).get('structuredContent', {})
        if not result.get('ok'):
            continue
        data = result.get('result', {})
        if item.get('tool') == 'worktree_claim':
            assert data['session_id'] == thread
            claim = data
        if item.get('tool') == 'task_start':
            active = [t['id'] for t in data['tasks'] if t['status'] == 'in_progress']
            assert len(active) == 1
            task_id = active[0]
        if item.get('tool') == 'delegation_wave_prepare' and len(data.get('dispatch_required', [])) == 2:
            assert claim and process and task_id == item['arguments']['task_id']
            prepared = index
            wave_id, ready = data['wave_id'], data['dispatch_required']
        if item.get('tool') == 'delegation_prepare' and wave_id is not None and first_dispatch is None:
            first_dispatch = index
        if item.get('tool') == 'session_status' and blocks and first_dispatch is None:
            nonwaiting = index
        if item.get('tool') == 'delegation_wave_read' and data.get('wave_id') == wave_id:
            receipt = data.get('last_wait_denial')
            if receipt is not None:
                assert process and receipt.get('authority') == 'native-pre-tool-use'
                assert receipt.get('tool') in {'write_stdin', 'functions.write_stdin'}
                assert receipt.get('native_turn') == turn and receipt.get('process_id') == process['id']
                assert receipt.get('empty_input') is True and receipt.get('dispatch_required') == ready
                assert receipt.get('invocation_id') in blocks
                observation = receipt
            if data.get('all_succeeded') is True:
                assert set(data['states']) == set(ready)
                assert all(value == 'succeeded' for value in data['states'].values())
                succeeded = index
        if item.get('tool') == 'task_resolve' and data.get('all_terminal') is True:
            assert item['arguments']['task_id'] == task_id
            assert all(t['status'] == 'succeeded' for t in data['tasks'])
            resolved = index
        if item.get('tool') == 'worktree_release' and data.get('released') is True:
            assert claim and data['claim'] == claim
            released = index
    assert process and observation and claim
    denied = blocks[observation['invocation_id']]
    assert None not in (prepared, nonwaiting, first_dispatch, succeeded, resolved, released, exited)
    assert process['index'] < prepared < denied < nonwaiting < first_dispatch < exited < resolved < released
    assert first_dispatch < succeeded < resolved
    return {'status': 'passed', 'thread': thread, 'turn': turn,
            'process_id': process['id'], 'wave_id': wave_id, 'task_id': task_id,
            'evidence': ['events.jsonl', 'hooks.json', 'completion.json']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codex-bin', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    probe(args.project.resolve(), args.output.resolve(), args.codex_bin, args.model)
