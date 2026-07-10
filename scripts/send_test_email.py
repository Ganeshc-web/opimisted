"""Send a test email using the app's embedded email_service.

Usage:
  python scripts/send_test_email.py
  python scripts/send_test_email.py recipient@example.com
  flask send-test-email
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from app.services.email_service import send_test_email


def main():
    to_email = sys.argv[1] if len(sys.argv) > 1 else None
    app = create_app()
    with app.app_context():
        recipient = send_test_email(to_email)
    print(f"Test email sent to {recipient}")


if __name__ == "__main__":
    main()
