import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "production"))


def _run_pending_migrations():
    if os.environ.get("FLASK_ENV", "production") != "production":
        return
    try:
        from flask_migrate import upgrade

        with app.app_context():
            upgrade()
    except Exception as exc:
        app.logger.warning("Database migration skipped or failed: %s", exc)


_run_pending_migrations()
