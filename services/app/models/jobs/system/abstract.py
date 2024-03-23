from extensions import db, get_session
from models.jobs.abstract import Job
from logs.config import setup_logger
from constants import OK, system, PROCESSING
from overrides import overrides
from models.users import User

class JobSystem(Job):

    logger = setup_logger('models.job_system')
    __tablename__ = 'job_system'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    root_name = db.Column(db.String(80), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "job_system",
        "polymorphic_on": "type"
    }

    def __init__(self, root_name="ICT Hotline"):
        super().__init__()
        self.root_name = root_name
        self.status = PROCESSING

    @property
    def root_user(self):
        if not getattr(self, '_root_user', None):
            session = get_session()
            self.root_user = session.query(User).filter_by(name=self.root_name).first()
        return self._root_user

    @root_user.setter
    def root_user(self, value):
        self._root_user = value

    @overrides
    def validate_complete(self):
        if self.status == OK and self.all_messages_successful():
            return True
        return False
        
    @classmethod
    def create_job(cls, intent=None, *args, **kwargs):
        if intent == system['MAIN']:
            new_job = cls(*args, **kwargs)
        elif intent == system['ACQUIRE_TOKEN']:
            from .acq_token import JobAcqToken
            new_job = JobAcqToken(*args, **kwargs)
        elif intent == system['AM_REPORT']:
            from .am_report import JobAmReport
            new_job = JobAmReport(*args, **kwargs)
        # Add conditions for other subclasses
        elif intent == system['SYNC_USERS']:
            from .sync_users import JobSyncUsers
            new_job =  JobSyncUsers(*args, **kwargs)
        elif intent == system['SYNC_LEAVE_RECORDS']:
            from .sync_leave_records import JobSyncRecords
            new_job =  JobSyncRecords(*args, **kwargs)
        elif intent == system['INDEX_DOCUMENT']:
            pass # TODO
        else:
            raise ValueError(f"Unknown intent ID: {intent}")
        new_job.error = False
        session = get_session()
        session.add(new_job)
        session.commit()
        return new_job