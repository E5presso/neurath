"""Verify unfinished-task Stop continuation in an already trusted native project.

The probe creates its own read-only app-server thread. It never changes trust,
claims, current app processes, or task state outside that native test thread.
"""
import argparse
import json
from pathlib import Path

from native_host import Host


def verify_stop_events(events, thread, turn):
    early = blocked = resolved = final = completed = None
    task_id = None
    for index, event in enumerate(events):
        params = event.get('params', {})
        if params.get('threadId') != thread or params.get('turnId') != turn:
            continue
        item = params.get('item', {})
        if event.get('method') == 'item/completed':
            if item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer':
                if item.get('text') == 'NEURATH_EARLY_STOP_PROBE':
                    early = index
                if item.get('text') == 'NEURATH_STOP_PROBE_OK':
                    final = index
            if item.get('type') == 'mcpToolCall':
                result = (item.get('result') or {}).get('structuredContent', {})
                task = result.get('result', {}).get('task', {})
                if result.get('ok') and item.get('tool') == 'task_start':
                    assert task.get('state') == 'running'
                    task_id = task['id']
                if result.get('ok') and item.get('tool') == 'task_complete':
                    assert task_id and task.get('id') == task_id and task.get('state') == 'completed'
                    resolved = index
        if event.get('method') == 'hook/completed':
            run = params.get('run', {})
            if run.get('eventName') != 'stop':
                continue
            if run.get('status') == 'blocked':
                assert task_id and task_id in json.dumps(run.get('entries', []))
                blocked = index
            if run.get('status') == 'completed':
                completed = index
    assert None not in (early, blocked, resolved, final, completed)
    assert early < blocked < resolved < final < completed
    return task_id


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
        })['thread']['id']
        prompt = (
            'Run this explicitly authorized read-only Neurath Stop regression. '
            'Use named session_status and task_list, then define and start exactly one task '
            'whose acceptance is observing the native unfinished-task Stop denial in this thread. '
            'Do not claim the worktree, edit files, spawn children, change settings or trust, '
            'or create phase workflows. Display each returned native TODO. '
            'For this bounded fault-injection test, intentionally attempt one final response '
            'NEURATH_EARLY_STOP_PROBE while that task is still running. '
            'When the host blocks Stop with the unfinished-task diagnostic and resumes you, '
            'read task_list, use report_record and task_complete on only this test task using the actually observed '
            'Stop denial as its acceptance evidence, display TODO and finish with NEURATH_STOP_PROBE_OK. '
            'Do not complete before the actual Stop denial. Do not invent failure or a receipt. '
            'All actions are confined to this independently created native test thread.'
        )
        turn = host.request('turn/start', {'threadId': thread,
            'input': [{'type': 'text', 'text': prompt}]})['turn']['id']
        print(json.dumps({'thread': thread, 'turn': turn, 'output': str(output)}), flush=True)
        event = host.wait(lambda e: e.get('method') == 'turn/completed'
            and e.get('params', {}).get('threadId') == thread, timeout=900)
        (output / 'completion.json').write_text(json.dumps(event, indent=2))
        assert event['params']['turn']['status'] == 'completed', event
        task_id = verify_stop_events(host.events, thread, turn)
        report = {'status': 'passed', 'thread': thread, 'turn': turn,
                  'task_id': task_id,
                  'evidence': ['events.jsonl', 'hooks.json', 'completion.json']}
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        host.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--codex-bin', default='codex')
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    probe(args.project.resolve(), args.output.resolve(), args.codex_bin, args.model)
