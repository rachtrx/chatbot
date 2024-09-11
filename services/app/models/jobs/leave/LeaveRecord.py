import shortuuid
from sqlalchemy import func

from extensions import db, Session
from MessageLogger import setup_logger

from models.jobs.base.constants import Status
from models.jobs.base.utilities import get_latest_date_past_hour, current_sg_time

from models.jobs.leave.Job import JobLeave
from models.jobs.leave.constants import LeaveStatus, AM_HOUR

class LeaveRecord(db.Model):

    logger = setup_logger('models.leave_records')

    __tablename__ = "leave_records"

    id = db.Column(db.String(32), primary_key=True, nullable=False)
    # name = db.Column(db.String(80), nullable=False)
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), nullable=False)

    date = db.Column(db.Date(), nullable=False)
    sync_status = db.Column(db.String(10), default=None, nullable=True)

    job = db.relationship('JobLeave', backref=db.backref('leave_records'), lazy='select')
    leave_status = db.Column(db.String(32), nullable=False)

    def __init__(self, job_no, date, leave_status):
        self.id = shortuuid.ShortUUID().random(length=8).upper()
        # self.name = user.name
        self.job_no = job_no
        self.date = date
        self.leave_status = leave_status

    @classmethod
    def get_all_leaves(cls, start_date=None, end_date=None, status=LeaveStatus.CONFIRMED):

        from models.users import User

        if not end_date:
            end_date = start_date

        session = Session()
        query = session.query(
            cls.id,
            cls.date,
            User.name,
            JobLeave.leave_type,
            User.dept,
            cls.job_no
        ).join(
            JobLeave, JobLeave.job_no == cls.job_no
        ).join(
            User, JobLeave.primary_user_id == User.id
        ).filter(
            cls.leave_status == status,
        )

        if end_date:
            query = query.filter(
                cls.date <= end_date
            )
        else:
            query = query.filter(
                cls.date >= start_date
            )

        # Execute the query
        all_records_today = query.all()

        cls.logger.info("All records today: ")
        cls.logger.info(all_records_today)

        return all_records_today

    @classmethod
    def get_duplicates(cls, leave_task):
        session = Session()
        duplicate_records = session.query(cls).join(
            JobLeave
        ).filter(
            JobLeave.primary_user_id == leave_task.user_id,
            cls.date >= leave_task.start_date,
            cls.date <= leave_task.end_date,
            cls.leave_status == LeaveStatus.CONFIRMED,
        ).all()

        return duplicate_records

    @classmethod
    def add_leaves(cls, job_no, dates, leave_status=LeaveStatus.CONFIRMED): # RequestAuthorisation
        session = Session()
        new_records = []
        for date in dates:
            new_record = cls(job_no=job_no, date=date, leave_status=leave_status)
            new_record.sync_status = Status.PENDING
            session.add(new_record)
            new_records.append(new_record)
        session.commit()

        return new_records

    @classmethod
    def update_leaves(cls, records, status):

        session = Session()
        dates = []

        with session.begin_nested():
            for record in records:
                record.leave_status = status
                record.sync_status = Status.PENDING
                dates.append(record.date)
            session.commit()

        return dates

    @classmethod
    def get_records(cls, job_no, statuses, past_hour=AM_HOUR):
        session = Session()
        query = session.query(cls).filter(cls.job_no == job_no)

        # filter records based on 'past_hour'
        if past_hour:
            query = query.filter(cls.date >= get_latest_date_past_hour(past_hour))

        # Conditionally filter records based on 'status'
        if statuses:
            query = query.filter(cls.leave_status.in_(statuses))

        return query.all()
