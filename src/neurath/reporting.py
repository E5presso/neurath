"""Opt-in, harness-only upstream reports with immutable drafts and bounded delivery."""

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from neurath import __version__
from neurath.install.transaction import canonical, read_state, repository
from neurath.resources import PACKAGE, manifest

UPSTREAM = "E5presso/neurath"
QUESTION = (
    "Neurath 공통 하네스의 결함·개선점을 발견하면 프로젝트 정보를 제외한 보고서를 "
    f"https://github.com/{UPSTREAM}/issues 에 공개해도 될까요? "
    "동의는 이 프로젝트에 저장되며 언제든 철회할 수 있습니다. "
    "프로젝트 전용 개선안은 공개할 초안에 대해 별도로 동의를 받습니다."
)
FIELDS = {"kind", "scope", "component", "summary", "expected", "observed", "reproduction", "proposal"}
PRIVATE = re.compile(
    r"(?i)(?:https?://|ssh://|git@|www\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
    r"(?:^|\s)(?:/|~/|[a-z]:\\)|(?:[\w.-]+[/\\]){2,}|"
    r"\b[\w.-]+[/\\][\w.-]+\.[a-z]{1,8}\b|"
    r"\b(?:sk-[\w-]{16,}|gh[pousr]_[\w]{20,}|github_pat_[\w]+)|"
    r"\b(?:[\w-]*(?:secret|password|token|api[_-]?key)|authorization)\s*[=:]|"
    r"\bBearer\s+|-----BEGIN|\b(?:\d{1,3}\.){3}\d{1,3}\b)"
)


class Reporting:
    def __init__(self, root):
        self.root = repository(root)
        common = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        )
        self.directory = Path(common.stdout.strip()) / "neurath-reporting"
        self.path = self.directory / "state.json"

    def _read(self):
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("reporting state must not be a symlink")
        if not self.path.exists():
            return {"schema": 1, "auto_report": None, "reports": {}}
        value = json.loads(self.path.read_text())
        if (not isinstance(value, dict) or value.get("schema") != 1
                or (value.get("auto_report") is not None
                    and type(value["auto_report"]) is not bool)
                or not isinstance(value.get("reports"), dict)):
            raise ValueError("invalid reporting state; publication disabled")
        return value

    @contextmanager
    def _locked(self):
        self._read()
        self.directory.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self._read()

    def _save(self, state):
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((canonical(state) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.chmod(0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def status(self):
        state = self._read()
        return {"auto_report": state["auto_report"], "consent_required": state["auto_report"] is None,
                "question": QUESTION if state["auto_report"] is None else None,
                "repository": UPSTREAM, "contribution_consent": "per-draft"}

    def consent(self, decision):
        """The native agent records only the current user's explicit decision."""
        if type(decision) is not bool:
            raise ValueError("consent decision must be boolean")
        with self._locked() as state:
            state["auto_report"] = decision
            self._save(state)
        return self.status()

    def _component(self, name, common):
        files = manifest()["files"]
        if not isinstance(name, str) or name not in files or name.startswith("templates/"):
            raise ValueError("component must identify a packaged Neurath file")
        path = PACKAGE / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != files[name]:
            raise ValueError("component differs from the packaged manifest")
        if common and name.startswith("_assets/"):
            from neurath.install.projection import asset_files
            from neurath.skill_names import public_name

            installed = read_state(self.root)
            if not installed:
                raise ValueError("component requires an installed harness")
            relative = name.removeprefix("_assets/")
            if relative.startswith(".agents/skills/"):
                parts = relative.split("/")
                parts[2] = public_name(parts[2], installed.get("skill_prefix", ""))
                relative = "/".join(parts)
            elif relative.startswith(".agents/rules/"):
                relative = relative.replace(".agents/rules/", ".neurath/rules/", 1)
            assets = asset_files(installed["profile"], installed["hosts"],
                                 installed.get("skill_prefix", ""))
            if relative in assets:
                target = self.root / relative
                if (target.is_symlink() or not target.is_file()
                        or target.read_bytes() != assets[relative][0]):
                    raise ValueError("customized component requires a contribution proposal")

    def _validate(self, data):
        if not isinstance(data, dict) or set(data) != FIELDS:
            raise ValueError("report fields must match the template exactly; no logs or attachments")
        if data["kind"] not in {"defect", "improvement", "contribution"}:
            raise ValueError("invalid report kind")
        if data["scope"] not in {"common", "project-specific"}:
            raise ValueError("invalid report scope")
        if data["scope"] != "common" and data["kind"] != "contribution":
            raise ValueError("project-specific work requires a contribution proposal")
        self._component(data["component"], data["kind"] != "contribution")
        private_names = {self.root.name.casefold()}
        remotes = subprocess.run(["git", "-C", str(self.root), "remote", "-v"],
                                 capture_output=True, text=True, check=True).stdout
        for remote in remotes.splitlines():
            url = remote.split()[1]
            # Only the exact public repository is exempt. A prefix match also
            # exempts private sibling repositories and unrelated forge hosts.
            upstream = re.fullmatch(
                r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
                + re.escape(UPSTREAM) + r"(?:\.git)?/?", url, re.IGNORECASE)
            if upstream is None:
                private_names.update(re.findall(r"[\w-]+", url.removesuffix(".git")))
        private_names -= {"neurath", "git", "github", "https", "ssh", "com", "origin"}
        for field in FIELDS - {"kind", "scope", "component"}:
            text = data[field]
            if (not isinstance(text, str) or not text.strip() or len(text) > 2400
                    or any(ord(char) < 32 and char != "\n" for char in text)
                    or any(marker in text for marker in ("```", "<", ">", "![", "]("))):
                raise ValueError("report must contain bounded generic prose only")
            if PRIVATE.search(text) or any(
                len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text.casefold())
                for name in private_names
            ):
                raise ValueError("possible private project content; rewrite as harness-only prose")
        if len(data["summary"]) > 140 or "\n" in data["summary"]:
            raise ValueError("summary must be a single short line")

    def prepare(self, data, *, privacy_reviewed=False):
        if privacy_reviewed is not True:
            raise ValueError("agent must review all fields for harness-only content first")
        self._validate(data)
        name = "contribution" if data["kind"] == "contribution" else "common-report"
        template = (PACKAGE / "templates" / f"{name}.md").read_text()
        payload = {"data": data, "title": f"[Neurath {data['kind']}] {data['summary']}",
                   "body": template.format(**data, version=__version__), "repository": UPSTREAM}
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self._locked() as state:
            state["reports"].setdefault(digest, {**payload, "id": digest, "status": "draft",
                                                "approved": False, "url": None})
            self._save(state)
            return dict(state["reports"][digest])

    def _draft(self, state, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid report ID")
        draft = state["reports"].get(digest)
        if not isinstance(draft, dict):
            raise ValueError("unknown report")
        payload = {key: draft[key] for key in ("data", "title", "body", "repository")}
        if (draft.get("id") != digest or draft["repository"] != UPSTREAM
                or hashlib.sha256(canonical(payload).encode()).hexdigest() != digest):
            raise ValueError("report content changed; prepare and approve a new draft")
        return draft

    def read(self, digest):
        return dict(self._draft(self._read(), digest))

    def list_reports(self):
        return [{key: draft[key] for key in ("id", "status", "url")}
                for draft in self._read()["reports"].values()]

    def approve(self, digest, *, decision):
        if type(decision) is not bool:
            raise ValueError("approval must be boolean")
        with self._locked() as state:
            draft = self._draft(state, digest)
            if draft["data"]["kind"] != "contribution" or draft["status"] != "draft":
                raise ValueError("approval requires an unsent contribution draft")
            draft["approved"] = decision
            self._save(state)
            return dict(draft)

    def submit(self, digest):
        # Serialize consent changes and sends across agents/worktrees. Persist before I/O:
        # a crash after GitHub accepted the issue must never cause an automatic duplicate.
        with self._locked() as state:
            draft = self._draft(state, digest)
            if draft["status"] != "draft":
                return dict(draft)
            if draft["data"]["kind"] == "contribution":
                if draft["approved"] is not True:
                    raise ValueError("exact contribution draft needs user approval")
            elif state["auto_report"] is not True:
                raise ValueError("automatic reporting consent is not enabled")
            self._validate(draft["data"])
            draft["status"] = "uncertain"
            self._save(state)
            try:
                draft["url"] = self._publish(draft)
                draft["status"] = "submitted"
            except (OSError, ValueError, subprocess.SubprocessError):
                draft["next_action"] = (
                    "Inspect the fixed upstream repository and authentication; do not resend. "
                    "Use reconcile with the existing issue URL if it was created."
                )
            self._save(state)
            return dict(draft)

    @staticmethod
    def _url(url):
        if not isinstance(url, str) or not re.fullmatch(
            r"https://github\.com/" + re.escape(UPSTREAM) + r"/issues/[1-9][0-9]*", url
        ):
            raise ValueError("unexpected upstream issue URL")
        return url

    @staticmethod
    def _gh(args, *, body=None):
        env = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1")
        # The fixed host/repository is supplied on every command; no project auto-detection.
        with tempfile.TemporaryDirectory(prefix="neurath-report-") as directory:
            if body is not None:
                path = Path(directory) / "body.md"
                path.write_text(body)
                path.chmod(0o600)
                args = [*args, "--body-file", str(path)]
            result = subprocess.run(["gh", *args, "--repo", "github.com/" + UPSTREAM],
                                    cwd=directory, env=env, capture_output=True, text=True,
                                    timeout=60, check=True)
        return result.stdout.strip()

    def _verify_issue(self, draft, url):
        self._url(url)
        value = json.loads(self._gh(["issue", "view", url, "--json", "url,title,body"]))
        if any(value.get(key) != expected for key, expected in
               (("url", url), ("title", draft["title"]), ("body", draft["body"]))):
            raise ValueError("upstream issue readback differs from approved report")
        return url

    def _publish(self, draft):
        url = self._url(self._gh(["issue", "create", "--title", draft["title"]], body=draft["body"]))
        return self._verify_issue(draft, url)

    def reconcile(self, digest, url):
        with self._locked() as state:
            draft = self._draft(state, digest)
            if draft["status"] != "uncertain":
                raise ValueError("only uncertain reports need reconciliation")
            draft["url"] = self._verify_issue(draft, url)
            draft["status"] = "submitted"
            draft.pop("next_action", None)
            self._save(state)
            return dict(draft)


def reporting_event(root, host, request, output):
    """Remind the active agent of consent/scope; hooks never collect or send reports."""
    if request.get("hook_event_name") not in {"SessionStart", "UserPromptSubmit"}:
        return output
    status = Reporting(root).status()
    if status["consent_required"]:
        notice = "Neurath reporting consent is pending. Ask the user once during onboarding: " + QUESTION
        notice += " Until an explicit answer, keep auto reporting disabled; never block the user's task."
    elif status["auto_report"]:
        notice = (
            "Neurath upstream reporting is enabled by the user. When a common harness defect or "
            "improvement is identified, use reporting_prepare then reporting_submit after a "
            "harness-only privacy review. Local fixes do not replace the upstream report. "
            "Project-specific work requires an exact contribution draft and separate user approval."
        )
    else:
        notice = "Neurath automatic upstream reporting is disabled. Do not ask again without user intent."
    result = dict(output)
    specific = dict(result.get("hookSpecificOutput", {}))
    specific.setdefault("hookEventName", request["hook_event_name"])
    previous = specific.get("additionalContext", "")
    specific["additionalContext"] = previous + ("\n\n" if previous else "") + notice
    result["hookSpecificOutput"] = specific
    return result
