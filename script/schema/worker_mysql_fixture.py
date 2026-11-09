"""Pure, standard-library admission of the owned ECS worker MySQL fixture.

The host controller and the ECS pytest suite share this exact validator. Import
does not load a test runner, database driver, application or external service.
"""
import json
from pathlib import Path
import re


def read_mysql_fixture(selected, project, identity):
    """Validate an explicit controller-owned disposable server before connecting."""
    file = Path(selected)
    if not file.is_absolute() or file.resolve(strict=True) != file or not file.is_file():
        raise ValueError('An absolute, non-redirected ECS MySQL fixture file is required')
    if not file.is_relative_to((project / 'work').resolve(strict=True)):
        raise ValueError('MySQL fixture must remain under project work')
    config = json.loads(file.read_text('utf-8'))
    if config.get('scope') != 'ecs-disposable-mysql' or any(
            config.get(key) != identity[key] for key in ('instanceId', 'machineId')):
        raise ValueError('MySQL fixture does not belong to the admitted ECS host')
    database = config.get('database', '')
    if not re.fullmatch(r'doorhandle_worker_verify_[a-f0-9]{10}', database):
        raise ValueError('An isolated worker database is required')
    account = 'ecsit_' + database.removeprefix('doorhandle_worker_verify_')
    port = config.get('port')
    if (config.get('username') != account or not isinstance(port, int) or isinstance(port, bool)
            or not 1024 < port <= 65535 or port == 3306 or not config.get('password')
            or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', config.get('serverUuid', ''))):
        raise ValueError('An explicit isolated worker account, port and MySQL identity are required')
    expected = (f'jdbc:mysql://127.0.0.1:{port}/{database}'
                '?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai')
    data = Path(config.get('dataDirectory', ''))
    if (config.get('url') != expected or not data.is_absolute() or not data.is_dir()
            or data.resolve(strict=True) != data or not data.is_relative_to(file.parent)):
        raise ValueError('MySQL data must belong to the explicit ECS attempt')
    return config


def assert_mysql_identity(actual, config):
    if (actual.get('db') != config['database']
            or not str(actual.get('account')).startswith(config['username'] + '@')
            or actual.get('uuid') != config['serverUuid'] or actual.get('port') != config['port']
            or Path(str(actual.get('data_directory'))).resolve(strict=True) != Path(config['dataDirectory'])):
        raise ValueError('Connected MySQL differs from the owned ECS fixture')
