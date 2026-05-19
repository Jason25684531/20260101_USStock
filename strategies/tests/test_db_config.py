from unittest.mock import patch

from utils.db import get_db_config


def test_get_db_config_defaults_to_trader_password_source():
    env = {
        "DB_HOST": "db",
        "DB_PORT": "3306",
        "DB_NAME": "usstock",
    }

    with patch("utils.db._SHARED_DB_MODULE.get_secret", side_effect=lambda name, default=None: default):
        config = get_db_config(env=env)

    assert config["user"] == "trader"
    assert config["password"] == "userpassword"


def test_get_db_config_uses_root_secret_only_for_root_user():
    env = {
        "DB_USER": "root",
        "DB_ROOT_PASSWORD": "root-secret",
        "DB_PASSWORD": "app-secret",
    }

    with patch("utils.db._SHARED_DB_MODULE.get_secret", side_effect=lambda name, default=None: default):
        config = get_db_config(env=env)

    assert config["user"] == "root"
    assert config["password"] == "root-secret"
