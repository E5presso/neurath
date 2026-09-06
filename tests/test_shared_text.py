"""Shared document edits retain their exact position through update and uninstall."""

import subprocess

import pytest

from neurath.doctor import doctor
from neurath.install.transaction import InstallError, apply_plan, make_plan


@pytest.mark.parametrize("path", ["AGENTS.md", "CLAUDE.md", ".gitignore"])
@pytest.mark.parametrize("original", [b"original without newline", b"original\r\n"])
def test_shared_edits_survive_update_uninstall_and_doctor_is_read_only(tmp_path, path, original):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    document = tmp_path / path
    document.write_bytes(original)
    apply_plan(tmp_path, make_plan(tmp_path))
    installed = document.read_bytes()
    edited = b"user prefix\n" + installed + b"user suffix\n"
    document.write_bytes(edited)
    state = (tmp_path / ".neurath/install.json").read_bytes()
    assert doctor(tmp_path)["placement"]["status"] == "passed"
    assert (tmp_path / ".neurath/install.json").read_bytes() == state
    apply_plan(tmp_path, make_plan(tmp_path, action="update"))
    assert document.read_bytes() == edited
    apply_plan(tmp_path, make_plan(tmp_path, action="uninstall"))
    assert document.read_bytes() == b"user prefix\n" + original + b"user suffix\n"


def test_new_shared_document_keeps_later_user_text(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    document = tmp_path / "AGENTS.md"
    document.write_bytes(document.read_bytes() + b"User instructions\n")
    apply_plan(tmp_path, make_plan(tmp_path, action="uninstall"))
    assert document.read_bytes() == b"User instructions\n"


@pytest.mark.parametrize("corruption", ["change", "duplicate", "delete", "symlink"])
def test_shared_managed_block_changes_still_conflict(tmp_path, corruption):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    document = tmp_path / "AGENTS.md"
    installed = document.read_text()
    if corruption == "change":
        document.write_text(installed.replace("generic", "edited"))
    elif corruption == "duplicate":
        document.write_text(installed + installed)
    elif corruption == "delete":
        document.write_text("user replacement\n")
    else:
        document.unlink()
        document.symlink_to("other.md")
    with pytest.raises(InstallError, match="conflict"):
        make_plan(tmp_path, action="update")


def test_shared_edit_after_plan_is_stale(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    document = tmp_path / "AGENTS.md"
    document.write_text("before\n" + document.read_text())
    plan = make_plan(tmp_path, action="update")
    document.write_text(document.read_text() + "after planning\n")
    with pytest.raises(InstallError, match="stale"):
        apply_plan(tmp_path, plan)
