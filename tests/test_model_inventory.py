"""Native model metadata is read without starting a model turn."""
import asyncio
import pytest
from neurath.providers.model_inventory import codex_inventory, claude_inventory


class Rpc:
    def __init__(self, pages):
        self.pages, self.calls = iter(pages), []
    def request(self, method, params):
        self.calls.append((method, params))
        assert method == "model/list"
        return next(self.pages)


def test_codex_paginates_without_creating_threads_or_inventing_default():
    rpc = Rpc([
        {"data": [{"id": "picker-a", "model": "exact-a", "isDefault": True,
                   "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                   "inputModalities": ["text"]}], "nextCursor": "next"},
        {"data": [{"id": "exact-b", "model": "exact-b"}], "nextCursor": None},
    ])
    result = codex_inventory(rpc, host="local")
    assert [m["id"] for m in result["models"]] == ["exact-a", "exact-b"]
    assert result["models"][0]["reasoning_efforts"] == ["high"]
    assert result["models"][1]["input_modalities"] is None
    assert result["default_model"] is None  # recommended != configured target default
    assert result["models"][0]["recommended"] is True
    assert rpc.calls[1][1]["cursor"] == "next"


@pytest.mark.parametrize("pages", [
    [{"data": [], "nextCursor": "x"}, {"data": [], "nextCursor": "x"}],
    [{"data": [{"model": "x"}, {"model": "x"}]}],
    [{"data": [{"model": "x", "supportedReasoningEfforts": "high"}]}],
    [{"data": [{"model": "x", "inputModalities": [12]}]}],
    {"bad": "shape"},
])
def test_malformed_inventory_is_never_partially_accepted(pages):
    rpc = Rpc(pages if isinstance(pages, list) else [pages])
    with pytest.raises(ValueError):
        codex_inventory(rpc, host="local")


def test_empty_and_missing_claude_inventory_remain_unavailable():
    assert asyncio.run(claude_inventory(None, host="local"))["status"] == "unavailable"
    class Client:
        async def get_server_info(self): return {"commands": []}
    assert asyncio.run(claude_inventory(Client(), host="local"))["models"] == []


def test_claude_only_reads_existing_client_and_preserves_unknown_capabilities():
    class Client:
        async def get_server_info(self):
            return {"models": [{"value": "exact-c", "displayName": "C", "description": "C model"}]}
        async def connect(self): pytest.fail("must not create a discovery session")
        async def query(self, *a): pytest.fail("must not start a model turn")
    result = asyncio.run(claude_inventory(Client(), host="local"))
    assert result["models"][0]["id"] == "exact-c"
    assert result["models"][0]["reasoning_efforts"] is None
    assert result["models"][0]["cost"] is None
    assert result["source"] == "claude-agent-sdk:get_server_info"

def test_fresh_claude_metadata_handshake_never_queries_and_always_disconnects():
    from neurath.providers.model_inventory import fresh_claude_inventory
    calls=[]
    class Client:
        def __init__(self,options):
            assert options.setting_sources==["user","project","local"]
            calls.append("options")
        async def connect(self): calls.append("connect")
        async def get_server_info(self): calls.append("info"); return {"models":[{"value":"exact"}]}
        async def disconnect(self): calls.append("disconnect")
        async def query(self,*a): pytest.fail("model query is forbidden")
    result=asyncio.run(fresh_claude_inventory("/tmp",host="local",client_factory=Client))
    assert result["models"][0]["id"]=="exact"
    assert calls==["options","connect","info","disconnect"]


def test_failed_claude_metadata_handshake_disconnects():
    from neurath.providers.model_inventory import fresh_claude_inventory
    calls=[]
    class Client:
        def __init__(self,options): pass
        async def connect(self): calls.append("connect")
        async def get_server_info(self): raise OSError("metadata failed")
        async def disconnect(self): calls.append("disconnect")
    with pytest.raises(OSError):
        asyncio.run(fresh_claude_inventory("/tmp",host="local",client_factory=Client))
    assert calls==["connect","disconnect"]

def test_metadata_process_strips_parent_identity(monkeypatch,tmp_path):
    import json
    from types import SimpleNamespace
    from neurath.providers.model_inventory import claude_inventory_process
    monkeypatch.setenv("NEURATH_ACTOR_ID","parent")
    monkeypatch.setenv("CODEX_THREAD_ID","parent-thread")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN","auth-setting")
    def run(argv,**kw):
        assert "NEURATH_ACTOR_ID" not in kw["env"]
        assert "CODEX_THREAD_ID" not in kw["env"]
        assert kw["env"]["CLAUDE_CODE_OAUTH_TOKEN"]=="auth-setting"
        assert "--claude-metadata" in argv and "--print" not in argv
        return SimpleNamespace(returncode=0,stdout=json.dumps({"provider":"claude-code","models":[]}))
    monkeypatch.setattr("subprocess.run",run)
    assert claude_inventory_process(tmp_path)["provider"]=="claude-code"
