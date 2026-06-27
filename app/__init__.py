import importlib

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_restx import Api
from flask_caching import Cache
from werkzeug.exceptions import BadRequest

from app.config import config_map
from app.core.exceptions import APIError
from app.core.swagger_models import init_swagger_models

db = SQLAlchemy()
migrate = Migrate()
cache = Cache()


def create_app(env="development"):
    app = Flask(__name__)
    app.config.from_object(config_map[env])

    db.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)

    from app.middleware.logger import init_logger
    init_logger(app)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        import uuid
        from flask import jsonify
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": e.message,
            "field": e.field,
            "request_id": str(uuid.uuid4())
        }), e.http_status

    api = Api(
        app,
        version="1.0.0",
        title="Wealth Wisdom — Financial Planning API",
        description=(
            "Retirement planning calculation API covering corpus "
            "projection, EPF accumulation, insurance needs, goal "
            "planning, and education/tour cost lookups.\n\n"
            "All monetary fields return three forms: `display` "
            "(rounded to 2dp), `raw` (full precision for chaining), "
            "and `inr` (human-readable Cr/L format).\n\n"
            "Authentication: pass your key in the `X-API-Key` header. "
            "User-role keys access calculation endpoints; admin-role "
            "keys can additionally update rates."
        ),
        doc="/api/docs",
        prefix="/api/v1",
        authorizations={"apikey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        security="apikey"
    )
    init_swagger_models(api)

    @api.errorhandler(APIError)
    def handle_restx_api_error(error):
        import uuid
        return {
            "status": "error",
            "code": error.code,
            "message": error.message,
            "field": error.field,
            "request_id": str(uuid.uuid4())
        }, error.http_status

    @api.errorhandler(BadRequest)
    def handle_restx_bad_request(error):
        import uuid

        errors = getattr(error, "data", {}).get("errors", {})
        field = next(iter(errors), None) if isinstance(errors, dict) else None
        message = str(errors) if errors else getattr(error, "description", str(error))
        return {
            "status": "error",
            "code": "INVALID_INPUT",
            "message": message,
            "field": field,
            "request_id": str(uuid.uuid4())
        }, 400

    @app.after_request
    def normalize_restx_validation_errors(response):
        if response.status_code != 400 or not response.is_json:
            return response

        payload = response.get_json(silent=True) or {}
        if "status" in payload or "errors" not in payload:
            return response

        import uuid
        from flask import jsonify

        errors = payload.get("errors") or {}
        field = next(iter(errors), None) if isinstance(errors, dict) else None
        normalized = jsonify({
            "status": "error",
            "code": "INVALID_INPUT",
            "message": str(errors) if errors else payload.get("message", "Invalid input."),
            "field": field,
            "request_id": str(uuid.uuid4())
        })
        normalized.status_code = 400
        return normalized

    from app.api.v1.health.routes import ns as health_ns
    from app.api.v1.rates.routes import ns as rates_ns
    from app.api.v1.assessment.routes import ns as assessment_ns
    from app.api.v1.calculate.routes import ns as calculate_ns
    from app.api.v1.report.routes import ns as report_ns
    from app.api.v1.education.routes import ns as education_ns
    from app.api.v1.tour.routes import ns as tour_ns

    api.add_namespace(health_ns)
    api.add_namespace(rates_ns)
    api.add_namespace(assessment_ns)
    api.add_namespace(calculate_ns)
    api.add_namespace(report_ns)
    api.add_namespace(education_ns)
    api.add_namespace(tour_ns)

    importlib.import_module("app.models")

    @app.route("/")
    def index():
        return {
            "message": "Financial Planning API",
            "docs": "/api/docs",
            "health": "/api/v1/health/",
        }

    @app.cli.command("seed-admin")
    def seed_admin():
        import secrets, hashlib
        from app.models.api_key import APIKey
        raw_key = secrets.token_hex(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        admin = APIKey(
            client_name="Admin",
            key_hash=key_hash,
            role="admin",
            is_active=True
        )
        db.session.add(admin)
        db.session.commit()
        print(f"\n ADMIN KEY (copy this — shown only once):\n {raw_key}\n")

    return app
