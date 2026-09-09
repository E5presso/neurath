"""A native issuer reuses one provider catalog across its worktrees and turns."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from neurath.providers.model_planning import Inventory, ModelInfo
from neurath.runtime.model_tasks import InventoryStore


CATALOG = Inventory("codex", "local", "native:model/list", "first",
                    models=(ModelInfo("available"),), observed_at=1)


def test_session_catalog_is_reused_without_another_provider_connection(tmp_path):
    store = InventoryStore(tmp_path / "plans.sqlite3")
    calls = []

    def discover():
        calls.append(1)
        return CATALOG

    first = store.session_inventory("issuer", "codex", discover)
    second = store.session_inventory("issuer", "codex", discover)
    assert first == second == CATALOG
    assert calls == [1]
    a = store.save("issuer", str(tmp_path / "a"), first)
    b = store.save("issuer", str(tmp_path / "b"), second)
    assert a != b  # Target authorization remains separate from catalog caching.
    assert store.read("issuer", a["inventory_id"], str(tmp_path / "a")) == CATALOG


def test_explicit_catalog_refresh_replaces_only_the_owning_session(tmp_path):
    store = InventoryStore(tmp_path / "plans.sqlite3")
    store.session_inventory("issuer", "codex", lambda: CATALOG)
    store.session_inventory("other", "codex", lambda: CATALOG)
    newer = replace(CATALOG, revision="second", observed_at=2)
    assert store.session_inventory("issuer", "codex", lambda: newer, refresh=True) == newer
    assert store.session_inventory("other", "codex", lambda: pytest.fail("queried again")) == CATALOG
    assert store.session_inventory("issuer", "codex", lambda: pytest.fail("queried again")) == newer


def test_concurrent_catalog_requests_discover_once(tmp_path):
    store = InventoryStore(tmp_path / "plans.sqlite3")
    calls = []

    def discover():
        calls.append(1)
        return CATALOG

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(
            lambda _: store.session_inventory("issuer", "codex", discover), range(4)))
    assert results == [CATALOG] * 4
    assert calls == [1]


def test_catalog_failure_does_not_replace_last_success_or_cache_foreign_provider(tmp_path):
    store = InventoryStore(tmp_path / "plans.sqlite3")
    store.session_inventory("issuer", "codex", lambda: CATALOG)

    def fail():
        raise RuntimeError("discovery failed")

    with pytest.raises(RuntimeError, match="discovery failed"):
        store.session_inventory("issuer", "codex", fail, refresh=True)
    assert store.session_inventory("issuer", "codex", fail) == CATALOG
    with pytest.raises(ValueError, match="provider"):
        store.session_inventory("issuer", "claude-code", lambda: CATALOG)


def test_catalog_discovery_does_not_hold_database_writer(tmp_path):
    import sqlite3
    store = InventoryStore(tmp_path / "plans.sqlite3")
    def discover():
        # Provider discovery may take time; unrelated control state must remain writable.
        with sqlite3.connect(store.plans.path, timeout=0) as other:
            other.execute("CREATE TABLE independent_progress(value TEXT)")
            other.execute("INSERT INTO independent_progress VALUES('available')")
        return CATALOG
    assert store.session_inventory("issuer", "codex", discover) == CATALOG
