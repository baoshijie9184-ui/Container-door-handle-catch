"""Execution guard boundaries; run this suite on the admitted ECS as well."""
from unittest.mock import Mock
import pytest
from scripts import ecs_execution as execution


def test_non_linux_is_rejected_before_metadata(monkeypatch):
    monkeypatch.setattr(execution.platform, 'system', lambda: 'Windows')
    opener = Mock()
    monkeypatch.setattr(execution, 'build_opener', opener)
    with pytest.raises(RuntimeError, match='edit/build only'):
        execution.require_ecs_execution()
    opener.assert_not_called()


@pytest.mark.parametrize('instance,machine', [('', ''), ('i-abc', ''), ('bad', 'a' * 32)])
def test_unbound_identity_is_rejected(monkeypatch, instance, machine):
    monkeypatch.setattr(execution.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('DOORHANDLE_ECS_INSTANCE_ID', instance)
    monkeypatch.setenv('DOORHANDLE_ECS_MACHINE_ID', machine)
    with pytest.raises(RuntimeError, match='Explicit ECS'):
        execution.require_ecs_execution()


def test_wrong_machine_never_contacts_metadata(monkeypatch):
    monkeypatch.setattr(execution.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('DOORHANDLE_ECS_INSTANCE_ID', 'i-abc')
    monkeypatch.setenv('DOORHANDLE_ECS_MACHINE_ID', 'a' * 32)
    monkeypatch.setattr(execution.Path, 'read_text', lambda _self: 'b' * 32)
    opener = Mock()
    monkeypatch.setattr(execution, 'build_opener', opener)
    with pytest.raises(RuntimeError, match='machine identity differs'):
        execution.require_ecs_execution()
    opener.assert_not_called()


def test_wrong_instance_is_rejected(monkeypatch):
    monkeypatch.setattr(execution.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('DOORHANDLE_ECS_INSTANCE_ID', 'i-abc')
    monkeypatch.setenv('DOORHANDLE_ECS_MACHINE_ID', 'a' * 32)
    monkeypatch.setattr(execution.Path, 'read_text', lambda _self: 'a' * 32)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.side_effect = [b'token', b'i-wrong']
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(execution, 'build_opener', lambda *_args: opener)
    with pytest.raises(RuntimeError, match='instance identity differs'):
        execution.require_ecs_execution()


def test_worker_requires_explicit_kafka_endpoint(monkeypatch):
    from kafka_settings import KafkaWorkerSettings
    monkeypatch.delenv('KAFKA_BOOTSTRAP_SERVERS', raising=False)
    settings = KafkaWorkerSettings.from_env()
    with pytest.raises(ValueError, match='kafka_bootstrap_servers'):
        settings.validate()
    monkeypatch.setenv('KAFKA_BOOTSTRAP_SERVERS', 'ecs-broker:9092')
    assert KafkaWorkerSettings.from_env().kafka_bootstrap_servers == 'ecs-broker:9092'
