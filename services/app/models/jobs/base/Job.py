import shortuuid
import logging
import traceback

from extensions import db, get_session
from MessageLogger import setup_logger

from models.jobs.base.constants import JobType
from models.jobs.base.utilities import current_sg_time, log_instances

from sqlalchemy.orm import declared_attr

from sqlalchemy.types import Enum as SQLEnum

class BaseJob(db.Model): # system jobs

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')

    job_no = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True))
    primary_user_id = db.Column(db.ForeignKey("users.id"), nullable=True)
    primary_user = db.relationship('User', backref='jobs', lazy='select')
    type = db.Column(SQLEnum(JobType), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": JobType.DAEMON,
        "polymorphic_on": type
    }

    def __init__(self, primary_user_id=None):
        logging.info(f"current time: {current_sg_time()}")
        self.job_no = shortuuid.ShortUUID().random(length=8)
        self.logger.info(f"new job: {self.job_no}")
        self.created_at = current_sg_time()
        self.primary_user_id = primary_user_id

    @classmethod
    def create_job(cls, intent, *args, **kwargs):
        new_job = None
        if intent == JobType.DAEMON:
            from models.jobs.daemon.Job import JobDaemon
            new_job = JobDaemon(*args, **kwargs)
        elif intent == JobType.LEAVE:
            from models.jobs.leave.Job import JobLeave
            new_job = JobLeave(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == JobType.ES_SEARCH:
            pass
        elif intent == JobType.UNKNOWN:
            pass
        if not new_job:
            raise ValueError(f"Unknown intent: {intent}")
        session = get_session()
        session.add(new_job)
        session.commit()
        return new_job.job_no
    
    def execute(self):
        raise NotImplementedError("This method should be implemented by subclasses")

    def cleanup_on_error(self):
        raise NotImplementedError("Please define a cleanup function")
    
    def get_latest_tasks(self):
        session = get_session()
        return session.query(self.state_model)\
            .filter(self.state_model.job_no == self.job_no)\
            .order_by(self.state_model.timestamp.desc())\
            .first()