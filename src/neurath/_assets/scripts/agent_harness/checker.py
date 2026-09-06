"""Check the kit distribution and managed installation, independent of project shape."""
from pathlib import Path
from scripts.agent_harness.violation import Violation

class AgentHarnessChecker:
    def __init__(self, root: Path):
        self._root = root.resolve()

    def check(self):
        from neurath.doctor import doctor, integrity
        from neurath.resources import PACKAGE
        result = []
        distribution = integrity()
        for error in distribution["errors"]:
            result.append(Violation("NH001", PACKAGE / error, "kit distribution integrity failed"))
        if (self._root / ".neurath").is_dir():
            placement = doctor(self._root)["placement"]
            for error in placement["errors"]:
                result.append(Violation("NH002", self._root / error, "managed installation differs from receipt"))
        return result
