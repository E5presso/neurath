"""Plan and commit conservative installations under one recoverable journal.

Read-only snapshot, configuration and record helpers live below this transaction
boundary. Compatibility exports retain existing installer callers while new
readers can use those narrower modules directly.
"""

import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

from neurath import __version__
from neurath.install.configuration import (
    _checkout_bootstrap, _migrate_checkout_bootstrap,
    _rebase_codex_config as _rebase_codex_config,
    rebase_shared,
)
from neurath.install.desired import InstallationProjection
from neurath.serialization import canonical as canonical
from neurath.install.file_values import (
    InstallError, bytes_of, file_value, git_dir, repository, safe_path, snapshot,
)
from neurath.install.projection import HOSTS, PROFILES
from neurath.install.records import (
    STATE, _read_receipt, installation_state_matches, read_state,
)
from neurath.install.state_store import InstallStateStore, projection
from neurath.resources import distribution_id
from neurath.skill_names import validate_skill_prefix


def make_plan(root, *, action="install", profile=None, hosts=None, receipt=None, skill_prefix=None):
    root = repository(root)
    from neurath.install.transition import require_cutover, transition_plan
    require_cutover(root)
    if (InstallStateStore(root).journal() is not None
            or (git_dir(root) / "neurath-journal.json").exists()):
        raise InstallError("interrupted transaction: run neurath recover")
    if action not in {"install", "update", "uninstall", "restore"}:
        raise InstallError("unsupported action")
    state = read_state(root)
    saved = _read_receipt(root, receipt) if action == "restore" else None
    before_state = state
    after_state = state
    if action == "restore":
        if "before_state" in saved:
            after_state = saved["before_state"]
        else:
            legacy = next(
                item["before"] for item in saved["changes"] if item["path"] == STATE
            )
            after_state = json.loads(bytes_of(legacy)) if legacy else None
    recorded_prefix = (
        state.get("skill_prefix", "") if state else
        saved.get("skill_prefix", "") if saved else ""
    )
    try:
        validate_skill_prefix(recorded_prefix)
        skill_prefix = validate_skill_prefix(
            recorded_prefix if skill_prefix is None else skill_prefix
        )
    except ValueError as error:
        raise InstallError(str(error)) from error
    if (state or action in {"restore", "uninstall"}) and skill_prefix != recorded_prefix:
        raise InstallError(
            "skill prefix differs from the installation record; uninstall before changing it"
        )
    profile = profile or (state["profile"] if state else "generic")
    hosts = sorted(set(hosts or (state["hosts"] if state else HOSTS)))
    if profile not in PROFILES or not hosts or any(host not in HOSTS for host in hosts):
        raise InstallError("unsupported profile or hosts")
    distribution = distribution_id()
    checks = {STATE: snapshot(root, STATE)}
    changes = []

    def observe(path):
        current = snapshot(root, path)
        checks[path] = current
        # Bind existing parent symlinks/directories to the reviewed plan as well.
        for ancestor in PurePosixPath(path).parents:
            if str(ancestor) != ".":
                checks.setdefault(str(ancestor), snapshot(root, str(ancestor)))
        return current

    def change(path, after):
        before = observe(path)
        if before != after:
            changes.append({"path": path, "before": before, "after": after})

    owned = dict(state["owned"]) if state else {}
    # Once edited, project bindings belong to the repository and are never restored away.
    project_binding = ".neurath/project.json"
    if project_binding in owned and observe(project_binding) != owned[project_binding]["installed"]:
        del owned[project_binding]
    for path, record in owned.items():
        current = observe(path)
        if (_checkout_bootstrap(root, path, current)
                and record["installed"] != current):
            owned[path] = _migrate_checkout_bootstrap(root, path, record, current)
        else:
            owned[path] = rebase_shared(path, record, current)
    if action == "restore":
        for item in saved["changes"]:
            observed = observe(item["path"])
            matches = (installation_state_matches(root, item["after"],
                       **({"expected_state": saved["after_state"]} if "after_state" in saved else {}))
                       if item["path"] == STATE else observed == item["after"])
            if not matches:
                raise InstallError(f"restore conflict: {item['path']}")
        for item in reversed(saved["changes"]):
            if item["path"] == STATE:
                continue
            change(item["path"], item["before"])
        state_value = None if after_state is None else file_value(
            (canonical(projection(after_state)) + "\n").encode(), 0o600
        )
        change(STATE, state_value)
    elif action == "uninstall":
        after_state = None
        for path, record in owned.items():
            change(path, record["original"])
        if state:
            change(STATE, None)
    else:
        desired_projection = InstallationProjection(root, owned, observe)
        desired = desired_projection.build(profile, hosts, skill_prefix)

        new_owned = {}
        for path, after in desired.items():
            before = desired_projection.original(path)
            new_owned[path] = {"original": before, "installed": after}
            change(path, after)
        for path, record in owned.items():
            if path not in desired:
                change(path, record["original"])
        after_state = {
            "schema": 1,
            "version": __version__,
            "distribution": distribution,
            "profile": profile,
            "hosts": hosts,
            "skill_prefix": skill_prefix,
            "owned": new_owned,
        }
        change(
            STATE,
            file_value((canonical(projection(after_state)) + "\n").encode(), 0o600),
        )
    plan = {
        "schema": 1,
        "root": str(root),
        "distribution": distribution,
        "action": action,
        "profile": profile,
        "hosts": hosts,
        "skill_prefix": skill_prefix,
        "receipt": receipt,
        "before_state": before_state,
        "after_state": after_state,
        "checks": checks,
        "changes": changes,
        "core_transition": transition_plan(root),
    }
    plan["id"] = hashlib.sha256(canonical(plan).encode()).hexdigest()
    return plan



def _write(root, relative, value):
    path = safe_path(root, relative)
    if value is None:
        if path.exists() or path.is_symlink():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if value["kind"] == "symlink":
        target = value["target"]
        resolved = (path.parent / target).resolve()
        if not resolved.is_relative_to(root):
            raise InstallError(f"symlink target escapes: {relative}")
        temporary = path.with_name(path.name + ".neurath-tmp")
        if temporary.exists() or temporary.is_symlink():
            raise InstallError(f"temporary path conflict: {temporary}")
        try:
            temporary.symlink_to(target)
            temporary.replace(path)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(bytes_of(value))
            file.flush()
            os.fsync(file.fileno())
        try:
            temporary.chmod(value["mode"])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temp = Path(file.name)
        file.write((canonical(value) + "\n").encode())
        file.flush()
        os.fsync(file.fileno())
    temp.chmod(0o600)
    temp.replace(path)

def _prune_skill_directories(root, changes):
    """Remove only empty ancestors of successfully retired, owned skill files."""
    directories = set()
    for item in changes:
        parts = PurePosixPath(item["path"]).parts
        if (item["after"] is None and len(parts) > 3
                and parts[:2] == (".agents", "skills")):
            for length in range(3, len(parts)):
                directories.add(PurePosixPath(*parts[:length]))
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try:
            safe_path(root, str(directory)).rmdir()
        except (OSError, InstallError):
            # User additions and cosmetic cleanup failures never invalidate an installation.
            pass

def apply_plan(root, plan):
    root = repository(root)
    from neurath.install.transition import require_cutover
    require_cutover(root)
    if plan.get("root") != str(root):
        raise InstallError("plan belongs to another repository")
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = InstallStateStore(root)
        if (existing.journal() is not None
                or (control / "neurath-journal.json").exists()):
            raise InstallError("interrupted transaction: run neurath recover")
        for path, expected_value in plan.get("checks", {}).items():
            if snapshot(root, path) != expected_value:
                raise InstallError(f"stale plan: {path}")
        expected = make_plan(
            root,
            action=plan["action"],
            profile=plan["profile"],
            hosts=plan["hosts"],
            receipt=plan.get("receipt"),
            skill_prefix=plan.get("skill_prefix"),
        )
        if expected != plan:
            raise InstallError("stale or modified plan: regenerate with this distribution")
        from neurath.install.transition import apply_transition
        with apply_transition(root, plan.get("core_transition")):
            if not plan["changes"]:
                return {"id": plan["id"], "changed": 0}
            store = InstallStateStore(root, create=True)
            try:
                store.import_legacy_files(control)
                store.ensure_state(plan["before_state"])
                store.begin(plan)
            except ValueError as error:
                raise InstallError(str(error)) from error
            applied = []
            try:
                for item in plan["changes"]:
                    if snapshot(root, item["path"]) != item["before"]:
                        raise InstallError(f"concurrent change: {item['path']}")
                    _write(root, item["path"], item["after"])
                    applied.append(item)
            except BaseException:
                rollback_conflict = False
                for item in reversed(applied):
                    if snapshot(root, item["path"]) == item["after"]:
                        _write(root, item["path"], item["before"])
                    elif snapshot(root, item["path"]) != item["before"]:
                        rollback_conflict = True
                if not rollback_conflict:
                    store.discard(plan["id"])
                raise
            try:
                store.finish(plan, plan["after_state"])
            except ValueError as error:
                raise InstallError(str(error)) from error
            _prune_skill_directories(root, plan["changes"])
            return {"id": plan["id"], "changed": len(plan["changes"])}

def recover(root):
    root = repository(root)
    control = git_dir(root)
    with (control / "neurath-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = InstallStateStore(root, create=True)
        try:
            store.import_legacy_files(control)
            plan = store.journal()
        except ValueError as error:
            raise InstallError(str(error)) from error
        if plan is None:
            return {"recovered": False}
        if plan["root"] != str(root):
            raise InstallError("journal root mismatch")
        for item in plan["changes"]:
            if snapshot(root, item["path"]) not in (item["before"], item["after"]):
                raise InstallError(f"recovery conflict: {item['path']}")
        for item in reversed(plan["changes"]):
            _write(root, item["path"], item["before"])
        store.discard(plan["id"])
        return {"recovered": True}
