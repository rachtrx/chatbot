from extensions import db
from sqlalchemy import func, not_
from MessageLogger import setup_logger
from utilities import get_latest_date_past_9am, print_all_dates
import json
import time
import shortuuid
from datetime import timedelta, datetime
from utilities import get_latest_date_past_9am, get_session, current_sg_time
from constants import LeaveStatus
from sqlalchemy.types import Enum as SQLEnum

class LeaveRecord(db.Model):

    logger = setup_logger('models.leave_records')

    __tablename__ = "leave_records"
    id = db.Column(db.String(80), primary_key=True, nullable=False)
    # name = db.Column(db.String(80), nullable=False)
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), nullable=False)
    cancelled_job_no = db.Column(db.ForeignKey("job_leave_cancel.job_no"), nullable=True)

    date = db.Column(db.Date(), nullable=False)
    sync_status = db.Column(db.Integer, default=None, nullable=True)

    job = db.relationship('JobLeave', backref=db.backref('leave_records'), lazy='select')
    leave_status = db.Column(SQLEnum(LeaveStatus), nullable=False)

    def __init__(self, job, date, leave_status=LeaveStatus.PENDING):
        self.id = shortuuid.ShortUUID().random(length=8)
        # self.name = user.name
        self.job_no = job.job_no
        self.date = date
        self.leave_status = leave_status
        session = get_session()
        session.add(self)
        session.commit()

    # @property
    # def user(self):
    #     from models.users import User
    #     if not getattr(self, '_user', None):
    #         session = get_session()
    #         self.user = session.query(User).filter_by(name=self.name).first()

    #     return self._user

    @classmethod
    def get_all_leaves_today(cls):
        from models.jobs.user.leave import JobLeave
        from models.users import User
        session = get_session()
        all_records_today = session.query(
            cls.date,
            func.concat(User.name, ' (', JobLeave.leave_type, ')').label('name'),
            User.dept,
        ).join(JobLeave).join(User, JobLeave.name == User.name).filter(
            cls.date == current_sg_time().date(),
            cls.is_cancelled == False
        ).all()

        return all_records_today

    @classmethod
    def get_duplicates(cls, job):
        from models.jobs.user.leave import JobLeave
        session = get_session()
        duplicate_records = session.query(cls).join(
            JobLeave
        ).filter(
            JobLeave.name == job.user.name,
            cls.date >= job.start_date,
            cls.date <= job.end_date,
            cls.is_cancelled == False
        ).all()

        return duplicate_records

    @classmethod
    def add_leaves(cls, job):
        session = get_session()
        for date in job.dates_to_update:
            new_record = cls(job=job, date=date)
            session.add(new_record)
        session.commit()

        return f"Dates added for {print_all_dates(job.dates_to_update, date_obj=True)}"

    @classmethod
    def update_leaves(cls, records, cancel_job, status=LeaveStatus.CANCELLED):

        session = get_session()
        dates_to_update = []

        with session.begin_nested():
            for record in records:
                record.leave_status = status
                record.sync_status = None
                record.cancelled_job_no = cancel_job.job_no
                dates_to_update.append(record.date)
            session.commit()

        cancel_job.duration = len(dates_to_update)
        cancel_job.dates_to_update = dates_to_update

        return f"Dates removed for {print_all_dates(dates_to_update, date_obj=True)}"

    @classmethod
    def get_records(cls, job, ignore_statuses, past_9am=True):
        session = get_session()
        query = session.query(cls).filter(cls.job_no == job.original_job.job_no)

        # filter records based on 'past_9am'
        if past_9am:
            query = query.filter(cls.date >= get_latest_date_past_9am())

        # Conditionally filter records based on 'status'
        if ignore_statuses:
            query = query.filter(not_(cls.leave_status.in_(ignore_statuses)))

        return query.all()
