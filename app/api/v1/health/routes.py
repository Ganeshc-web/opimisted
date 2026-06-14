import time
from datetime import datetime
from flask_restx import Namespace, Resource
from app import db
from app.middleware.auth import require_admin
from app.core.formulas import PF_MONTHLY_RATE

START_TIME = time.time()

ns = Namespace("health", description="Server health", path="/health")


@ns.route("/")
class Health(Resource):
    def get(self):
        """Public health check. Pinged by load balancer."""
        return {
            "status": "ok",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat()
        }


@ns.route("/detailed")
class HealthDetailed(Resource):
    @require_admin
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
            "timestamp": datetime.utcnow().isoformat()
        }
