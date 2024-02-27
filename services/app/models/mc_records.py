from extensions import db
# from sqlalchemy.orm import
from logs.config import setup_logger
from constants import MAX_UNBLOCK_WAIT
from utilities import get_relations_name_and_no_list
import json
import time
import uuid
from utilities import get_latest_date_past_8am

class McRecord(db.Model):

    logger = setup_logger('models.user')

    __tablename__ = "mc_records"
    id = db.Column(db.String(80), primary_key=True, nullable=False)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    job_no = db.Column(db.ForeignKey("job.job_no"), nullable=False)

    date = db.Column(db.Date(), nullable=False)
    type = db.Column(db.String(80), nullable=False)

    user = db.relationship('User', backref=db.backref('mc_records'))
    job = db.relationship('Job', backref=db.backref('mc_records'))

    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)


    def __init__(self, user, job, date, type):
        self.id = uuid.uuid4().hex
        self.user_id = user.id
        self.job = job
        self.date = date
        self.type = type
        db.session.add(self)
        db.session.commit()

    @classmethod
    def commit_cancel(cls, job):
        
        relevant_records = cls.query.filter(
            cls.job_no == job.job_no,
            cls.date >= get_latest_date_past_8am()
        ).all()

        for record in relevant_records:
            record.is_cancelled = True
        
        db.session.commit()

    @classmethod
    def check_for_duplicates(cls, job, user):
        
        duplicates = cls.query.filter(
            cls.user_id == user.user_id,
            cls.date >= job.start_date,
            cls.date <= job.end_date
        ).all()

        if not duplicates:
            return False
        else:
            return [duplicate.date for duplicate in duplicates]
        
    @classmethod
    def get_all_dates_for_user(cls, job, user):
    

