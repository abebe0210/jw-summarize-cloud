from __future__ import annotations

import logging
from collections.abc import Callable

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from .auth import authorize_request
from .cloud_pipeline import (
    CloudPipelineService,
    CloudProcessRequest,
    is_cloud_process_payload,
)
from .config import Settings
from .exceptions import AuthError, ConfigError, JWSummarizeError, ValidationError
from .github_publisher import GitHubPublisher
from .local_publisher import LocalPublisher
from .models import ProcessingRequest
from .service import SummaryGenerator, SummarizationService

load_dotenv()

LOGGER = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    publisher_factory: Callable[[Settings], object] | None = None,
    summary_generator: SummaryGenerator | None = None,
    cloud_service_factory: Callable[[Settings], CloudPipelineService] | None = None,
) -> Flask:
    resolved_settings = settings or Settings.from_env()
    resolved_publisher_factory = publisher_factory or _default_publisher_factory
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/process")
    def process():
        cloud_payload = False
        try:
            authorize_request(request, resolved_settings)
            payload = request.get_json(force=True, silent=False)
            cloud_payload = is_cloud_process_payload(payload)
            if cloud_payload:
                cloud_request = CloudProcessRequest.from_mapping(payload)
                cloud_service = (
                    cloud_service_factory(resolved_settings)
                    if cloud_service_factory
                    else CloudPipelineService(
                        settings=resolved_settings,
                        summary_generator=summary_generator,
                    )
                )
                result = cloud_service.process(cloud_request)
                return jsonify({"status": "done", **result.to_dict()})

            job = ProcessingRequest.from_mapping(payload)
            publisher = resolved_publisher_factory(resolved_settings)
            service = SummarizationService(
                settings=resolved_settings,
                publisher=publisher,
                summary_generator=summary_generator,
            )
            result = service.process(job)
            return jsonify({"status": "success", **result.to_dict()})
        except AuthError as exc:
            return jsonify({"status": "error", "error_message": str(exc)}), 401
        except ValidationError as exc:
            return jsonify({"status": "error", "error_message": str(exc)}), 400
        except (ConfigError, JWSummarizeError) as exc:
            LOGGER.exception("Application error while processing request")
            status = "retrying" if cloud_payload else "error"
            return jsonify({"status": status, "error_message": str(exc)}), 500
        except Exception as exc:  # pragma: no cover - safety net
            LOGGER.exception("Unexpected error while processing request")
            status = "retrying" if cloud_payload else "error"
            return (
                jsonify({"status": status, "error_message": f"Unexpected error: {exc}"}),
                500,
            )

    return app


def _default_publisher_factory(settings: Settings):
    if settings.github_enabled:
        return GitHubPublisher(settings)
    return LocalPublisher(settings.local_output_dir)


app = create_app()
