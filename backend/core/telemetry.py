import logging
import os
from urllib.parse import urlsplit

from fastapi import FastAPI

logger = logging.getLogger(__name__)
_TELEMETRY_STATE_KEY = "naruon_telemetry_configured"


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _otel_endpoint_has_hostname(endpoint: str) -> bool:
    raw_endpoint = endpoint.strip()
    if not raw_endpoint:
        return False

    parsed_endpoint = urlsplit(raw_endpoint)
    if parsed_endpoint.netloc:
        return parsed_endpoint.hostname is not None

    if "://" in raw_endpoint:
        return False

    return urlsplit(f"//{raw_endpoint}").hostname is not None


def setup_telemetry(app: FastAPI):
    if getattr(app.state, _TELEMETRY_STATE_KEY, False):
        logger.debug("OpenTelemetry instrumentation is already configured.")
        return

    # Only set up tracing when ENABLE_OTEL is true and an OTLP endpoint is set.
    enable_otel = _env_flag("ENABLE_OTEL")
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not enable_otel or not otel_endpoint:
        logger.info("OpenTelemetry is disabled.")
        return

    if not _otel_endpoint_has_hostname(otel_endpoint):
        logger.error(
            "Invalid OTEL exporter endpoint URL: missing hostname; "
            "continuing without tracing."
        )
        return

    otlp_insecure = _env_flag("OTEL_EXPORTER_OTLP_INSECURE")

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        logger.info("Setting up OpenTelemetry export.")
        resource = Resource(attributes={SERVICE_NAME: "naruon-backend"})

        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        otlp_exporter = OTLPSpanExporter(
            endpoint=otel_endpoint,
            insecure=otlp_insecure,
        )
        span_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(span_processor)

        FastAPIInstrumentor.instrument_app(app)
        setattr(app.state, _TELEMETRY_STATE_KEY, True)
        logger.info("OpenTelemetry instrumentation completed successfully.")
    except Exception:
        logger.exception("OpenTelemetry setup failed; continuing without tracing.")
