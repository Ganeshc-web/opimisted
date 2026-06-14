import uuid
import time
import logging
from flask import request, g

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("financial_api")


def init_logger(app):
    @app.before_request
    def before():
        g.request_id = str(uuid.uuid4())
        g.start_time = time.time()
        logger.info(
            f"→ {request.method} {request.path} | "
            f"request_id={g.request_id} | "
            f"ip={request.remote_addr}"
        )

    @app.after_request
    def after(response):
        duration_ms = round((time.time() - g.get("start_time", time.time())) * 1000, 2)
        logger.info(
            f"← {request.method} {request.path} | "
            f"status={response.status_code} | "
            f"duration={duration_ms}ms | "
            f"request_id={g.get('request_id', '-')}"
        )
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        return response
