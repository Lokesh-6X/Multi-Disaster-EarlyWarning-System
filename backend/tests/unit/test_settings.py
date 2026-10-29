"""Settings from .env (design/01 §1.7.3, NFR-08)."""
import pytest

from ews.common.settings import Settings, SettingsError, load_settings

FULL = """\
# comment
DATABASE_URL=postgresql://ews:dbpw@localhost:5432/ews
DEMO_DATABASE_URL=postgresql://ews:dbpw@localhost:5432/ews_demo
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_INGEST_USER=ingest
MQTT_INGEST_PASSWORD=mqttpw
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=ews@localhost
SMTP_TLS=false
APP_BASE_URL=http://localhost:8000
DEV_ORIGINS=
SECRET_KEY=abcdefghijklmnopqrstuvwxyz012345
OPEN_METEO_FORECAST_URL=https://api.open-meteo.com/v1/forecast
OPEN_METEO_ARCHIVE_URL=https://archive-api.open-meteo.com/v1/archive
MODELS_DIR=models
LOG_DIR=logs
LOG_LEVEL=INFO
EWS_CLOCK=real
"""


@pytest.fixture(autouse=True)
def clean_environ(monkeypatch):
    """Real environment variables must not leak into the tests."""
    import ews.common.settings as s
    for name in s.ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path, text=FULL):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_all_variables(tmp_path):
    s = load_settings(write_env(tmp_path))
    assert isinstance(s, Settings)
    assert s.database_url.endswith("/ews")
    assert s.mqtt_port == 1883 and s.smtp_port == 1025
    assert s.smtp_tls is False
    assert s.dev_origins == []
    assert s.clock_mode == "real"
    assert s.log_level == "INFO"


def test_missing_env_file_fails_with_clear_message(tmp_path):
    with pytest.raises(SettingsError, match=r"\.env not found.*\.env\.example"):
        load_settings(tmp_path / ".env")


def test_missing_variables_are_all_named(tmp_path):
    text = "\n".join(l for l in FULL.splitlines() if not l.startswith(("DATABASE_URL=", "SECRET_KEY=")))
    with pytest.raises(SettingsError) as e:
        load_settings(write_env(tmp_path, text))
    assert "DATABASE_URL" in str(e.value) and "SECRET_KEY" in str(e.value)


def test_empty_required_variable_is_missing(tmp_path):
    with pytest.raises(SettingsError, match="MQTT_HOST"):
        load_settings(write_env(tmp_path, FULL.replace("MQTT_HOST=localhost", "MQTT_HOST=")))


def test_optional_variables_may_be_empty(tmp_path):
    s = load_settings(write_env(tmp_path))
    assert s.smtp_user == "" and s.smtp_password == ""


def test_environment_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert load_settings(write_env(tmp_path)).log_level == "DEBUG"


@pytest.mark.parametrize("line, message", [
    ("MQTT_PORT=abc", "MQTT_PORT"),
    ("EWS_CLOCK=fast", "EWS_CLOCK"),
    ("LOG_LEVEL=LOUD", "LOG_LEVEL"),
    ("SMTP_TLS=maybe", "SMTP_TLS"),
])
def test_invalid_values_are_rejected(tmp_path, line, message):
    key = line.split("=")[0]
    text = "\n".join(line if l.startswith(key + "=") else l for l in FULL.splitlines())
    with pytest.raises(SettingsError, match=message):
        load_settings(write_env(tmp_path, text))


def test_demo_mode_needs_demo_database(tmp_path):
    """11 §11.3.1: demo mode uses its own database."""
    text = FULL.replace("EWS_CLOCK=real", "EWS_CLOCK=demo").replace(
        "DEMO_DATABASE_URL=postgresql://ews:dbpw@localhost:5432/ews_demo", "DEMO_DATABASE_URL=")
    with pytest.raises(SettingsError, match="DEMO_DATABASE_URL"):
        load_settings(write_env(tmp_path, text))


def test_demo_mode_uses_demo_database(tmp_path):
    s = load_settings(write_env(tmp_path, FULL.replace("EWS_CLOCK=real", "EWS_CLOCK=demo")))
    assert s.active_database_url.endswith("/ews_demo")


def test_real_mode_uses_main_database(tmp_path):
    assert load_settings(write_env(tmp_path)).active_database_url.endswith("/ews")


def test_dev_origins_are_split(tmp_path):
    s = load_settings(write_env(tmp_path, FULL.replace("DEV_ORIGINS=", "DEV_ORIGINS=http://localhost:5173, http://127.0.0.1:5173")))
    assert s.dev_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_relative_dirs_resolve_against_env_file(tmp_path):
    s = load_settings(write_env(tmp_path))
    assert s.log_dir == tmp_path / "logs" and s.models_dir == tmp_path / "models"


def test_repr_hides_secrets(tmp_path):
    """NFR-08: printing the settings (e.g. in process.started) never shows a secret."""
    text = repr(load_settings(write_env(tmp_path)))
    for secret in ("dbpw", "mqttpw", "abcdefghijklmnopqrstuvwxyz012345"):
        assert secret not in text
    assert "postgresql://ews:***@localhost:5432/ews" in text


def test_quoted_values_are_unquoted(tmp_path):
    s = load_settings(write_env(tmp_path, FULL.replace("SMTP_FROM=ews@localhost", 'SMTP_FROM="EWS <ews@localhost>"')))
    assert s.smtp_from == "EWS <ews@localhost>"
