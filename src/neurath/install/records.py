"""Validated reads of canonical installation state and retained receipts.

Visible state is a reference projection. Semantic comparison permits only the
validated schema migration; all other snapshot bytes and modes stay exact.
"""

import hashlib
import json
import re
from pathlib import Path

from neurath.serialization import canonical
from neurath.install.file_values import InstallError, bytes_of, git_dir, snapshot
from neurath.install.state_store import InstallStateStore, projection
from neurath.skill_names import validate_skill_prefix

STATE = ".neurath/install.json"
_STATE_UNSPECIFIED = object()

def read_state(root):
    value = snapshot(Path(root), STATE)
    try:
        visible = json.loads(bytes_of(value)) if value else None
    except (ValueError, TypeError) as error:
        raise InstallError("invalid installation state") from error
    canonical_state = InstallStateStore(root).state()
    if visible is None:
        if canonical_state is not None:
            raise InstallError("installation state projection is missing")
        return None
    if not isinstance(visible, dict):
        raise InstallError("invalid installation state")
    if visible.get("schema") == 2:
        if canonical_state is None or visible != projection(canonical_state):
            raise InstallError("installation state reference mismatch")
        state = canonical_state
    else:
        state = visible
        if canonical_state is not None and canonical_state != state:
            raise InstallError("installation state differs from canonical SQLite state")
    if state is not None and (state.get("schema") != 1 or not isinstance(state.get("owned"), dict)):
        raise InstallError("unsupported installation state")
    if state is not None:
        try:
            validate_skill_prefix(state.get("skill_prefix", ""))
        except ValueError as error:
            raise InstallError("invalid installation skill prefix") from error
    return state

def installation_state_matches(root, expected, *, expected_state=_STATE_UNSPECIFIED):
    """Allow only a validated schema-1/schema-2 representation difference.

    Same-schema content and permissions stay exact. The validated semantic state
    must agree with its saved bytes and with the current canonical state.
    """
    current = snapshot(Path(root), STATE)
    actual_state = read_state(root)
    try:
        expected_visible = json.loads(bytes_of(expected)) if expected is not None else None
        current_visible = json.loads(bytes_of(current)) if current is not None else None
    except (TypeError, ValueError) as error:
        raise InstallError("invalid installation state comparison") from error
    if expected_state is _STATE_UNSPECIFIED:
        if expected_visible is None or (isinstance(expected_visible, dict)
                                       and expected_visible.get("schema") == 1):
            expected_state = expected_visible
        else:
            # Without the validated state payload, only exact representation is allowed.
            return current == expected
    if expected_state is not None:
        if (not isinstance(expected_state, dict) or expected_state.get("schema") != 1
                or not isinstance(expected_state.get("owned"), dict)):
            raise InstallError("invalid expected canonical installation state")
        try:
            validate_skill_prefix(expected_state.get("skill_prefix", ""))
        except ValueError as error:
            raise InstallError("invalid expected installation skill prefix") from error
    if expected_visible != expected_state and expected_visible != projection(expected_state):
        raise InstallError("saved installation bytes differ from expected canonical state")
    if actual_state != expected_state:
        return False
    if current == expected:
        return True
    return (isinstance(current, dict) and isinstance(expected, dict)
            and current.get("kind") == expected.get("kind") == "file"
            and current.get("mode") == expected.get("mode")
            and isinstance(current_visible, dict) and isinstance(expected_visible, dict)
            and {current_visible.get("schema"), expected_visible.get("schema")} == {1, 2})

def _read_receipt(root, receipt):
    if not isinstance(receipt, str) or re.fullmatch(r"[a-f0-9]{64}", receipt) is None:
        raise InstallError("invalid installation record ID")
    try:
        stored = InstallStateStore(root).receipt(receipt)
    except ValueError as error:
        raise InstallError(str(error)) from error
    if stored is not None:
        return stored
    path = git_dir(root) / "neurath-receipts" / f"{receipt}.json"
    try:
        result = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise InstallError("installation record unavailable") from error
    if not isinstance(result, dict) or result.get("root") != str(root) or result.get("id") != receipt:
        raise InstallError("installation record belongs to a different target or ID")
    content = {key: value for key, value in result.items() if key != "id"}
    if hashlib.sha256(canonical(content).encode()).hexdigest() != receipt:
        raise InstallError("installation record integrity mismatch")
    return result
