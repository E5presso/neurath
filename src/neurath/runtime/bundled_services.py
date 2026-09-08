"""Load only kit-owned service modules; task inputs never choose code paths."""
from functools import lru_cache
import importlib.util
import sys
from neurath.resources import BUNDLE

SERVICES = {
    "review": "process-ticket/scripts/delegate_state.py",
    "process": "process-ticket/scripts/process_state_evidence.py",
    "cleanup": "process-ticket/scripts/merge_cleanup.py",
    "publication": "pr-review/scripts/publish_final_review.py",
    "monitor": "monitor-pr/scripts/local_pr_monitor.py",
    "monitor_ack": "monitor-pr/scripts/acknowledge_event.py",
    "monitor_readback": "monitor-pr/scripts/monitor_runtime_readback.py",
    "monitor_handoff": "monitor-pr/scripts/monitor_runtime_handoff.py",
    "monitor_resources": "monitor-pr/scripts/monitor_runtime_resources.py",
    "monitor_resume": "monitor-pr/scripts/app_server_resume.py",
}


@lru_cache
def service(name):
    path = BUNDLE / ".agents/skills" / SERVICES[name]
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    module_name = "neurath_bundled_" + name
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Packaged service is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
