from datetime import date

from app import db


class ReportEmailDailyCount(db.Model):
    __tablename__ = "report_email_daily_count"

    day = db.Column(db.Date, primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
