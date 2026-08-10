import time
from datetime import datetime, timezone
from flask_restx import Namespace, Resource, fields
from app import db
from app.core.swagger_models import error_model
from app.middleware.auth import require_admin
from app.core.formulas import PF_MONTHLY_RATE

START_TIME = time.time()

ns = Namespace(
    "health",
    description=(
        "Operational health checks for uptime monitoring, database "
        "connectivity, and formula engine readiness."
    ),
    path="/health",
)

health_model = ns.model("HealthResponse", {
    "status": fields.String(
        required=True,
        description="Overall service status.",
        example="ok",
    ),
    "version": fields.String(
        required=True,
        description="API version currently served.",
        example="1.0.0",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the health response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})

detailed_health_model = ns.model("DetailedHealthResponse", {
    "status": fields.String(
        required=True,
        description="Overall service status after dependency checks.",
        example="ok",
    ),
    "uptime_seconds": fields.Integer(
        required=True,
        description="Number of seconds since this process started.",
        example=3600,
    ),
    "version": fields.String(
        required=True,
        description="API version currently served.",
        example="1.0.0",
    ),
    "database": fields.String(
        required=True,
        description="Database connectivity status.",
        example="ok",
    ),
    "formula_engine": fields.String(
        required=True,
        description="Formula engine readiness status.",
        example="ok",
    ),
    "timestamp": fields.String(
        required=True,
        description="UTC timestamp for the health response.",
        example="2026-06-27T13:30:00+00:00",
    ),
})


@ns.route("/")
class Health(Resource):
    @ns.doc(
        security=[],
        description=(
            "Public liveness check for load balancers and uptime monitors. "
            "Use this endpoint to confirm the API process is reachable."
        ),
    )
    @ns.response(200, "Success", health_model)
    def get(self):
        """Public health check. Pinged by load balancer."""
        return {
            "status": "ok",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@ns.route("/detailed")
class HealthDetailed(Resource):
    @require_admin
    @ns.doc(
        security="apikey",
        description=(
            "Admin-only readiness check that verifies database connectivity "
            "and core formula constants in addition to process uptime."
        ),
    )
    @ns.response(200, "Success", detailed_health_model)
    @ns.response(401, "Missing or invalid API key", error_model)
    @ns.response(403, "Insufficient permissions", error_model)
    def get(self):
        """Detailed health — DB and formula engine status. Admin only."""
        uptime = int(time.time() - START_TIME)

        db_status = "ok"
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception as e:
            db_status = f"error: {str(e)}"

        formula_status = "ok"
        try:
            assert round(PF_MONTHLY_RATE, 6) == round(0.006434, 6)
        except Exception:
            formula_status = "error: PF_MONTHLY_RATE mismatch"

        return {
            "status": "ok" if db_status == "ok" else "degraded",
            "uptime_seconds": uptime,
            "version": "1.0.0",
            "database": db_status,
            "formula_engine": formula_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
