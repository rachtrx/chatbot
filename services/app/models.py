from datetime import datetime
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import desc


class User(db.Model):

    __tablename__ = "user"
    name: Mapped[str] = mapped_column(db.String(80), primary_key=True, nullable=False)
    number: Mapped[int] = mapped_column(db.Integer(), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)

    # Self-referential relationships
    reporting_officer_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name'), nullable=True)
    reporting_officer = db.relationship('User', backref='subordinates', remote_side=[name], post_update=True, foreign_keys=[reporting_officer_name])
    
    hod_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name'), nullable=True)
    hod = db.relationship('User', backref='dept_members', remote_side=[name], post_update=True, foreign_keys=[hod_name])

    # primary key for McDetails
    mc_details = db.relationship('McDetails', backref="user", lazy=True)

    def __init__(self, name, number, email, reporting_officer=None, hod=None):
        self.name = name
        self.number = number
        self.email = email
        self.reporting_officer = reporting_officer
        self.hod = hod

# class ReportingOfficer(User):
#     __tablename__ = "reporting_officer"


# class SchoolLeader(ReportingOfficer):
#     __tablename__ = "school_leader"


class McDetails(db.Model):

    __tablename__ = "mc_details"
    id: Mapped[str] = mapped_column(db.String(50), nullable=False, primary_key=True)
    number: Mapped[int] = mapped_column(db.Integer(), nullable=False)
    name: Mapped[str] = mapped_column(db.String(50), db.ForeignKey('user.name'), nullable=False)
    start_date: Mapped[str] = mapped_column(db.String(20), nullable=False)
    end_date: Mapped[str] = mapped_column(db.String(20), nullable=False)
    duration: Mapped[str] = mapped_column(db.Integer, nullable=False)
    intent: Mapped[int] = mapped_column(db.Integer(), nullable=False)
    status: Mapped[int] = mapped_column(db.Integer(), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    def __init__(self, id, number, name, start_date, end_date, duration, intent, status, timestamp=(datetime.utcnow())):
        self.id = id
        self.number = number
        self.name = name
        self.start_date = start_date
        self.end_date = end_date
        self.duration = duration
        self.intent = intent
        self.status = status
        self.timestamp = timestamp