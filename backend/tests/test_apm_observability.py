import logging
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent

def test_observability_compose_file_exists():
    assert (ROOT_DIR / "docker-compose.infra.yml").exists()


def test_observability_provisioning_exists():
    assert (
        ROOT_DIR / "observability/grafana/provisioning/datasources/datasources.yaml"
    ).exists()
    assert (ROOT_DIR / "observability/prometheus.yml").exists()
    assert (ROOT_DIR / "observability/tempo.yaml").exists()


def test_backend_metrics_endpoint_is_disabled_by_default():
    from main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code == 404


def test_metrics_exposure_requires_explicit_environment_gate():
    main_source = (ROOT_DIR / "backend/main.py").read_text()

    assert "ENABLE_PROMETHEUS_METRICS" in main_source
    assert "Instrumentator().instrument(app).expose" in main_source


def test_open_telemetry_setup_is_centralized_and_opt_in_by_default():
    main_source = (ROOT_DIR / "backend/main.py").read_text()
    telemetry_source = (ROOT_DIR / "backend/core/telemetry.py").read_text()

    assert "setup_telemetry(app)" in main_source
    assert "FastAPIInstrumentor.instrument_app(app)" not in main_source
    assert '_env_flag("ENABLE_OTEL")' in telemetry_source
    assert 'os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")' in telemetry_source
    assert '"http://localhost:4317"' not in telemetry_source
    assert "OTEL_EXPORTER_OTLP_INSECURE" in telemetry_source
    assert "insecure=otlp_insecure" in telemetry_source
    assert "except Exception" in telemetry_source


def test_telemetry_does_not_instrument_without_explicit_endpoint(monkeypatch):
    from fastapi import FastAPI
    from core import telemetry

    app = FastAPI()
    monkeypatch.delenv("ENABLE_OTEL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    telemetry.setup_telemetry(app)

    assert getattr(app.state, "naruon_telemetry_configured", False) is False


def test_otel_endpoint_hostname_validation_accepts_urls_and_hostports():
    from core.telemetry import _otel_endpoint_has_hostname

    assert _otel_endpoint_has_hostname("http://localhost:4317")
    assert _otel_endpoint_has_hostname("https://collector.example.com")
    assert _otel_endpoint_has_hostname("localhost:4317")
    assert _otel_endpoint_has_hostname("collector.example.com")
    assert not _otel_endpoint_has_hostname("")
    assert not _otel_endpoint_has_hostname("http://")
    assert not _otel_endpoint_has_hostname(":4317")


def test_telemetry_logs_error_on_missing_hostname(monkeypatch, caplog):
    from fastapi import FastAPI
    from core import telemetry

    app = FastAPI()
    monkeypatch.setenv("ENABLE_OTEL", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://")
    caplog.set_level(logging.ERROR, logger=telemetry.logger.name)

    telemetry.setup_telemetry(app)

    telemetry_records = [
        record for record in caplog.records if record.name == telemetry.logger.name
    ]
    assert getattr(app.state, "naruon_telemetry_configured", False) is False
    assert [record.getMessage() for record in telemetry_records] == [
        "Invalid OTEL exporter endpoint URL: missing hostname; continuing without tracing."
    ]
    assert telemetry_records[0].exc_info is None
