import importlib

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_restx import Api

from app.config import config_map
from app.core.exceptions import APIError

db = SQLAlchemy()
migrate = Migrate()


def create_app(env="development"):
    app = Flask(__name__)
    app.config.from_object(config_map[env])

    db.init_app(app)
    migrate.init_app(app, db)

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
        title="Financial Planning API",
        description="Retirement planning calculation API",
        doc="/api/docs",
        prefix="/api/v1",
        authorizations={"apikey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        security="apikey"
    )

    from app.api.v1.health.routes import ns as health_ns
    from app.api.v1.rates.routes import ns as rates_ns
    from app.api.v1.assessment.routes import ns as assessment_ns
    from app.api.v1.calculate.routes import ns as calculate_ns
    from app.api.v1.report.routes import ns as report_ns

    api.add_namespace(health_ns)
    api.add_namespace(rates_ns)
    api.add_namespace(assessment_ns)
    api.add_namespace(calculate_ns)
    api.add_namespace(report_ns)

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
