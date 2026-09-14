"""Source-bound JSONL recovery for pull migration, excluding private reasoning."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from neurath.memory.store import ProjectMemory, canonical, clean, control_root


def registered_path(value, host):
    """Locate only the registered file or its exact native Codex archive move."""
    path=Path(value)
    if path.exists() or host!='codex':
        return path
    storage=next((parent for parent in path.parents if parent.name=='sessions'),None)
    if storage is None:
        return path
    archived=storage.parent/'archived_sessions'/path.name
    if archived.is_symlink() or not archived.resolve().is_relative_to(storage.parent.resolve()):
        raise ValueError('archived transcript is outside its registered host storage')
    return archived if archived.is_file() else path


def _path(value):
    if value.startswith('file://'):
        value=unquote(urlparse(value).path)
    return Path(value).resolve()


def _text(blocks):
    if isinstance(blocks,str):
        return clean(blocks)
    if not isinstance(blocks,list):
        return ''
    return clean('\n'.join(b.get('text','') for b in blocks if isinstance(b,dict)
        and b.get('type') in ('text','input_text','output_text') and isinstance(b.get('text'),str)))


def _safe(value):
    if isinstance(value,dict):
        if value.get('type') in ('reasoning','thinking','redacted_thinking','Reasoning'):
            return {'omitted':'private-reasoning'}
        return {k:('[REDACTED]' if k in ('_neurath_binding','fencing_token') else _safe(v))
                for k,v in value.items()}
    if isinstance(value,list):
        return [_safe(v) for v in value]
    if isinstance(value,str):
        if value.lstrip().startswith(('{','[')):
            try:
                decoded=json.loads(value)
            except ValueError:
                pass
            else:
                return canonical(_safe(decoded))
        return clean(value)
    return value


def _object(value):
    if isinstance(value,str):
        try:
            value=json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value,dict) else {}


def _process_outcome(call, output, pending):
    """A yielded command response is not a process exit or a safe handoff."""
    result=_object(output)
    handle=result.get('session_id')
    if type(handle) is int and type(result.get('exit_code')) is not int:
        pending['process:'+str(handle)]='background-outcome-unobserved'
    if call and str(call.get('name','')).split('.')[-1]=='write_stdin':
        original=_object(call.get('input')).get('session_id')
        if type(original) is int and type(result.get('exit_code')) is int:
            pending.pop('process:'+str(original),None)


def inspect_transcript(path, host, session, root, *, include_entries=True, before_offset=None,
                       registered_transcript=None):
    from neurath.hosts.identity import host_storage
    path=Path(path)
    # The source journal already validated its native storage at registration.
    # A receiver can have a different CODEX_HOME / CLAUDE_CONFIG_DIR.
    registered = (registered_transcript is not None
                  and path.resolve() == Path(registered_transcript).resolve())
    if path.is_symlink() or (not registered and not path.resolve().is_relative_to(host_storage(host,os.environ).resolve())):
        raise ValueError('source transcript is outside its native host storage')
    entries=deque(maxlen=64)
    pending={}
    calls={}
    started=None
    closed=set()
    source_root=None
    total=0
    offset=0
    malformed=0
    fingerprint=hashlib.sha256()
    before=path.stat()
    with path.open('rb') as stream:
        for raw in stream:
            start=offset
            offset+=len(raw)
            fingerprint.update(raw)
            if not raw.endswith(b'\n'):
                offset=start
                break
            try:
                event=json.loads(raw)
            except (ValueError,UnicodeDecodeError):
                malformed+=1
                continue
            if not isinstance(event,dict):
                malformed+=1
                continue
            record=None
            extra=[]
            if host=='codex':
                p=event.get('payload',{})
                if not isinstance(p,dict):
                    continue
                if event.get('type')=='session_meta':
                    if p.get('id')!=session or not isinstance(p.get('cwd'),str):
                        raise ValueError('source transcript session metadata differs')
                    source_root=_path(p['cwd'])
                if event.get('type')=='turn_context':
                    started=p.get('turn_id')
                if event.get('type')=='event_msg':
                    if p.get('type')=='task_started':
                        started=p.get('turn_id')
                    if p.get('type') in ('task_complete','turn_aborted') and p.get('turn_id'):
                        closed.add(p['turn_id'])
                    item=p.get('item',{})
                    if (p.get('type')=='item_started' and p.get('thread_id')==session
                            and isinstance(item,dict) and item.get('type')=='CommandExecution'):
                        pending[item.get('id','unknown-command')]='command-outcome-unobserved'
                    if p.get('type')=='item_completed' and p.get('thread_id')==session and isinstance(item,dict):
                        kind=item.get('type')
                        if kind=='CommandExecution':
                            if source_root is None or not isinstance(item.get('cwd'),str) or _path(item['cwd'])!=source_root:
                                continue
                            code=item.get('exit_code')
                            if type(code) is int and item.get('status') in ('completed','failed'):
                                pending.pop(item.get('id'),None)
                                record={'kind':'tool','authority':'native-process-result','tool_id':item.get('id'),
                                    'command':item.get('command'),'exit_code':code,
                                    'output':clean(item.get('aggregated_output',''))[:4096]}
                            else:
                                pending[item.get('id','unknown-command')]='command-outcome-unobserved'
                        elif kind=='FileChange':
                            record={'kind':'file-change','authority':'native-tool-result','tool_id':item.get('id'),
                                    'status':item.get('status'),'changes':item.get('changes')}
                        elif kind=='McpToolCall':
                            result=item.get('result') or {}
                            record={'kind':'tool','authority':'native-tool-result','tool_id':item.get('id'),
                                'tool':item.get('tool'),'server':item.get('server'),'status':item.get('status'),
                                'result':result.get('structuredContent') if isinstance(result,dict) else None,
                                'error':item.get('error')}
                elif event.get('type')=='response_item':
                    kind=p.get('type')
                    if kind in ('function_call','custom_tool_call') and p.get('call_id'):
                        pending[p['call_id']]=p.get('name','tool')
                        calls[p['call_id']]={'name':p.get('name'), 'input':p.get('arguments',p.get('input'))}
                    elif kind in ('function_call_output','custom_tool_call_output'):
                        identity=p.get('call_id')
                        call=calls.pop(identity,None)
                        pending.pop(identity,None)
                        if call is None:
                            pending['unmatched-result:'+str(identity)]='original-call-unobserved'
                        _process_outcome(call,p.get('output'),pending)
                        record={'kind':'tool','authority':'reference-only','tool_id':identity,
                                'call':call,'output':p.get('output'),'native_exit_code':'unobserved'}
                    elif kind=='message' and p.get('role') in ('user','assistant') and p.get('phase') not in ('analysis','reasoning'):
                        text=_text(p.get('content'))
                        if text:
                            record={'kind':'prompt' if p['role']=='user' else 'assistant','authority':'reference-only','content':text}
            elif host=='claude-code':
                if event.get('sessionId')!=session or event.get('isSidechain'):
                    continue
                if isinstance(event.get('cwd'),str):
                    candidate=_path(event['cwd'])
                    if source_root is not None and candidate!=source_root:
                        raise ValueError('source transcript worktree changed')
                    source_root=candidate
                message=event.get('message')
                content=message.get('content',[]) if isinstance(message,dict) else []
                if event.get('type')=='assistant' and isinstance(content,list):
                    started='claude-last-turn'
                    closed.discard(started)
                    for block in content:
                        if isinstance(block,dict) and block.get('type')=='tool_use' and block.get('id'):
                            pending[block['id']]=block.get('name','tool')
                            calls[block['id']]={'name':block.get('name'),'input':block.get('input')}
                elif event.get('type')=='user' and isinstance(content,list):
                    for block in content:
                        if isinstance(block,dict) and block.get('type')=='tool_result':
                            identity=block.get('tool_use_id')
                            call=calls.pop(identity,None)
                            pending.pop(identity,None)
                            result=event.get('toolUseResult')
                            if call is None:
                                pending['unmatched-result:'+str(identity)]='original-call-unobserved'
                            if isinstance(result,dict) and any(result.get(k) for k in
                                    ('backgroundTaskId','background_task_id','interrupted')):
                                pending['background:'+str(identity)]='background-outcome-unobserved'
                            extra.append({'kind':'tool','authority':'reference-only','tool_id':identity,
                                'call':call,'output':block.get('content'),'native_result':result,
                                'native_is_error':block.get('is_error') if type(block.get('is_error')) is bool else None})
                if event.get('type') in ('user','assistant'):
                    text=_text(content)
                    if text:
                        record={'kind':'prompt' if event['type']=='user' else 'assistant',
                                'authority':'reference-only','content':text}
                if event.get('type')=='system' and event.get('subtype') in ('turn_duration','stop_hook_summary'):
                    closed.add('claude-last-turn')
                blocks=content if isinstance(content,list) else []
                if event.get('type')=='user' and not any(isinstance(b,dict) and b.get('type')=='tool_result' for b in blocks):
                    started='claude-last-turn'
                    closed.discard(started)
            else:
                raise ValueError('unsupported source transcript provider')
            if record is not None:
                extra.append(record)
            if include_entries and (before_offset is None or start<before_offset):
                for record in extra:
                    record=ProjectMemory._clean_data(_safe(record))
                    record['offset']=start
                    record['record_sha256']=hashlib.sha256(raw).hexdigest()
                    if len(canonical(record).encode())>16384:
                        record={'kind':record['kind'],'authority':record['authority'],'offset':start,
                                'record_sha256':record['record_sha256'],'content_omitted':True}
                    entries.append(record)
                    total+=1
    after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('source transcript changed while reading; retry with a new snapshot')
    if source_root is None or control_root(source_root)!=control_root(root):
        raise ValueError('source transcript has no matching Git project metadata')
    proof={'path':str(path.resolve()),'inode':after.st_ino,'size':after.st_size,'mtime_ns':after.st_mtime_ns,
           'sha256':fingerprint.hexdigest(),'complete_offset':offset}
    return {'status':'complete' if offset==after.st_size and not malformed else 'partial',
        'worktree':str(source_root),'fingerprint':proof,'entries':list(entries),'total_entries':total,
        'earlier_offset':entries[0]['offset'] if total>len(entries) else None,
        'pending_tools':sorted(str(k) for k in pending),'turn_closed':bool(started and started in closed),
        'malformed_records':malformed,'instruction':'Raw source data; do not infer current approval or tool success from text.'}
