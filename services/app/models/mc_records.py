from extensions import db
# from sqlalchemy.orm import
from logs.config import setup_logger
from constants import MAX_UNBLOCK_WAIT
from utilities import get_latest_date_past_8am, print_all_dates
import json
import time
import uuid
from datetime import timedelta
from utilities import get_latest_date_past_8am, run_new_context, get_session

class McRecord(db.Model):

    logger = setup_logger('models.mc_records')

    __tablename__ = "mc_records"
    id = db.Column(db.String(80), primary_key=True, nullable=False)
    name = db.Column(db.ForeignKey("users.name"), nullable=False)
    job_no = db.Column(db.ForeignKey("job.job_no"), nullable=False)

    date = db.Column(db.Date(), nullable=False)
    type = db.Column(db.String(80), nullable=False)

    user = db.relationship('User', backref=db.backref('mc_records'))
    job = db.relationship('Job', backref=db.backref('mc_records'))

    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)


    def __init__(self, user, job, date):
        self.id = uuid.uuid4().hex
        self.name = user.name
        self.job_no = job.job_no
        self.date = date
        self.type = job.leave_type
        self.commit()

    def commit(self):
        session = get_session()
        session.add(self)
        session.commit()

    @classmethod
    def get_duplicates(cls, job):
        session = get_session()
        duplicate_records = session.query(McRecord).filter(
            cls.name == job.user.name,
            cls.date >= job.start_date,
            cls.date <= job.end_date
        ).all()

        return duplicate_records

    @classmethod
    def insert_local_db(cls, job):
        session = get_session()
        for date in job.dates_to_update:
            new_record = cls(user=job.user, job=job, date=date)
            session.add(new_record)
        
        job.local_db_updated = True
        session.commit()

        return f"Dates added for {print_all_dates(job.dates_to_update, date_obj=True)}"

    @classmethod
    def delete_local_db(cls, job):
        session = get_session()
        records = session.query(cls).filter(
            cls.job_no == job.job_no,
            cls.date.in_(job.dates_to_update)
        ).all()

        with session.begin_nested():
            for record in records:
                session.delete(record)
            
            session.commit()

        return f"Dates removed for {print_all_dates(job.dates_to_update, date_obj=True)}"


