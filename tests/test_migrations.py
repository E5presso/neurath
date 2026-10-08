"""Versioned schema upgrades and failure recovery on temporary files only."""
from concurrent.futures import ThreadPoolExecutor
from alembic import command
import pytest
from sqlalchemy import inspect
from neurath.domain.models import Criterion, Task
from neurath.infrastructure import Database, MigrationError


def record():
    return Task(id='preserved', owner_id='original-owner', source_id='original-source', goal='Preserve data across versions', criteria=[Criterion('check', 'Original criterion')]).to_dict()


def version(database):
    with database.engine.connect() as connection:
        return connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()


def test_fresh_and_repeated_upgrade_packaged_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database = Database(tmp_path / 'new' / 'ledger.sqlite3')
    database.initialize()
    database.initialize()
    assert version(database) == '0002'
    assert {'tasks', 'records', 'leases', 'task_phases', 'source_archives'} <= set(inspect(database.engine).get_table_names())
    database.close()


def test_upgrade_from_0001_retains_data_and_downgrade_is_explicit(tmp_path):
    database = Database(tmp_path / 'ledger.sqlite3')
    database.initialize('0001')
    database.import_records({'task': [record()]})
    database.initialize()
    assert database.export_records()['task'] == [record()]
    database.import_records({}, snapshot_id='archive', archive={'old_rows': ['keep']})
    with pytest.raises(MigrationError):
        database.initialize('0001')
    database.downgrade('0001')
    assert version(database) == '0001'
    assert database.export_records()['task'] == [record()]
    assert database.read_archive('archive') == {'old_rows': ['keep']}
    database.initialize()
    assert version(database) == '0002'
    assert database.read_archive('archive') == {'old_rows': ['keep']}
    with pytest.raises(MigrationError):
        database.downgrade('base')
    database.close()


def test_failed_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    database = Database(tmp_path / 'ledger.sqlite3')
    database.initialize('0001')
    database.import_records({'task': [record()]})
    real_upgrade = command.upgrade
    def fail_after_ddl(config, target):
        real_upgrade(config, target)
        raise RuntimeError('simulated failure after DDL')
    with monkeypatch.context() as patch:
        patch.setattr(command, 'upgrade', fail_after_ddl)
        with pytest.raises(RuntimeError, match='simulated'):
            database.initialize()
    assert version(database) == '0001'
    assert 'source_archives' not in inspect(database.engine).get_table_names()
    assert database.export_records()['task'] == [record()]
    database.initialize()
    assert version(database) == '0002'
    database.close()


def test_unknown_future_and_unversioned_schema_fail_closed(tmp_path):
    database = Database(tmp_path / 'future.sqlite3')
    database.initialize()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num='9999'")
    with pytest.raises(MigrationError, match='future'):
        database.initialize()
    assert version(database) == '9999'
    database.close()
    unversioned = Database(tmp_path / 'unversioned.sqlite3')
    with unversioned.engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE foreign_data(id INTEGER)')
    with pytest.raises(MigrationError, match='explicit import'):
        unversioned.initialize()
    unversioned.close()


def test_concurrent_startup_serializes_upgrade(tmp_path):
    path = tmp_path / 'ledger.sqlite3'
    def start(_):
        database = Database(path)
        try:
            database.initialize()
            return version(database)
        finally:
            database.close()
    with ThreadPoolExecutor(max_workers=6) as executor:
        assert list(executor.map(start, range(12))) == ['0002'] * 12
