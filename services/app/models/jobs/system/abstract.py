from extensions import db
from models.jobs.abstract import Job
from logs.config import setup_logger
from constants import OK, system, PENDING
from overrides import overrides
from models.users import User

from utilities import run_new_context, get_session

class JobSystem(Job):

    logger = setup_logger('models.job_system')
    __tablename__ = 'job_system'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    root_name = db.Column(db.String(80), nullable=True)
    task_status = db.Column(db.Integer, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "job_system",
        "polymorphic_on": "type"
    }

    def __init__(self, root_name="ICT Hotline"):
        super().__init__()
        self.root_name = root_name
        self.task_status = OK

    @property
    def root_user(self):
        user = db.session.query(User).filter_by(name=self.root_name).first()
        return user

    @overrides
    def validate_complete(self):
        if self.task_status == OK and self.all_messages_successful():
            return True
        return False
    
    @classmethod
    def create_job(cls, intent, *args, **kwargs):
        if intent == system['ACQUIRE_TOKEN']:
            from .acq_token import JobAcqToken
            new_job = JobAcqToken(*args, **kwargs)
        elif intent == system['AM_REPORT']:
            from .am_report import JobAmReport
            new_job = JobAmReport(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == system['SYNC_USERS']:
            from .sync_users import JobSyncUsers
            new_job =  JobSyncUsers(*args, **kwargs)
        elif intent == system['INDEX_DOCUMENT']:
            pass # TODO
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        db.session.add(new_job)
        db.session.commit()
        return new_job