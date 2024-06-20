import shortuuid
from sqlalchemy import func
from sqlalchemy.types import Enum as SQLEnum

from extensions import db
from MessageLogger import setup_logger

from models.jobs.base.constants import Status
from models.jobs.base.utilities import get_latest_date_past_hour, get_session, current_sg_time

from models.jobs.leave.Job import JobLeave
from models.jobs.leave.constants import LeaveStatus

class LeaveRecord(db.Model):

    logger = setup_logger('models.leave_records')

    __tablename__ = "leave_records"
    id = db.Column(db.String(80), primary_key=True, nullable=False)
    # name = db.Column(db.String(80), nullable=False)
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), nullable=False)

    date = db.Column(db.Date(), nullable=False)
    sync_status = db.Column(SQLEnum(Status), default=None, nullable=True)

    job = db.relationship('JobLeave', backref=db.backref('leave_records'), lazy='select')
    leave_status = db.Column(SQLEnum(LeaveStatus), nullable=False)

    def __init__(self, job, date, leave_status):
        self.id = shortuuid.ShortUUID().random(length=8)
        # self.name = user.name
        self.job_no = job.job_no
        self.date = date
        self.leave_status = leave_status

    @classmethod
    def get_all_leaves_today(cls):
        from models.users import User
        session = get_session()
        all_records_today = session.query(
            cls.date,
            func.concat(User.name, ' (', JobLeave.leave_type, ')').label('name'),
            User.dept,
        ).join(
            JobLeave, JobLeave.job_no == cls.job_no
        ).join(
            User, JobLeave.user_id == User.id
        ).filter(
            cls.date == current_sg_time().date(),
            cls.leave_status == LeaveStatus.APPROVED,
        ).all()

        return all_records_today

    @classmethod
    def get_duplicates(cls, job):
        session = get_session()
        duplicate_records = session.query(cls).join(
            JobLeave
        ).filter(
            JobLeave.name == job.user.name,
            cls.date >= job.start_date,
            cls.date <= job.end_date,
            cls.leave_status.in_([LeaveStatus.PENDING, LeaveStatus.APPROVED])
        ).all()

        return duplicate_records

    @classmethod
    def add_leaves(cls, job_no, dates, leave_status=LeaveStatus.PENDING): # RequestAuthorisation
        session = get_session()
        new_records = []
        for date in dates:
            new_record = cls(job=job_no, date=date, leave_status=leave_status)
            session.add(new_record)
            new_records.append(new_record)
        session.commit()

        return new_records

    @classmethod
    def update_leaves(cls, records, status):

        session = get_session()
        dates = []

        with session.begin_nested():
            for record in records:
                record.leave_status = status
                record.sync_status = Status.PENDING
                dates.append(record.date)
            session.commit()

        return dates

    @classmethod
    def get_records(cls, job_no, statuses, past_9am=True):
        session = get_session()
        query = session.query(cls).filter(cls.job_no == job_no)

        # filter records based on 'past_9am'
        if past_9am:
            query = query.filter(cls.date >= get_latest_date_past_hour())

        # Conditionally filter records based on 'status'
        if statuses:
            query = query.filter(cls.leave_status.in_(statuses))

        return query.all()