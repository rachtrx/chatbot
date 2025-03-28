from extensions import db, get_session
from models.jobs.abstract import Job
from logs.config import setup_logger
from constants import OK, system, PROCESSING
from overrides import overrides
from models.users import User
from datetime import datetime, timedelta
from sqlalchemy import not_, exists, and_
import logging
from sqlalchemy.orm import aliased

class JobSystem(Job):

    logger = setup_logger('models.job_system')
    __tablename__ = 'job_system'

    job_no = db.Column(db.ForeignKey("job.job_no", ondelete='CASCADE'), primary_key=True)
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
    
    @classmethod
    def delete_old_jobs(cls):
        from models.messages.abstract import Message
        from models.metrics import Metric
        from .am_report import JobAmReport
        session = get_session()
        threshold = datetime.now() - timedelta(days=180)  # temporary

        job_system_alias = aliased(JobSystem, flat=True)

        # Subqueries for checking references
        message_subquery = session.query(Message.job_no).filter(Message.job_no == Job.job_no).subquery()
        metric_successful_subquery = session.query(Metric.last_successful_job_no).filter(Metric.last_successful_job_no == Job.job_no).subquery()
        metric_subquery = session.query(Metric.last_job_no).filter(Metric.last_job_no == Job.job_no).subquery()
        job_am_report_subquery = session.query(JobAmReport.job_no).filter(JobAmReport.job_no == Job.job_no).subquery()

        # Main query to select job numbers using aliased JobSystem
        job_nos = session.query(Job.job_no).join(job_system_alias).\
            filter(
                and_(
                    Job.created_at < threshold,
                    not_(exists().where(message_subquery.c.job_no == Job.job_no)),  # No reference in Message
                    not_(exists().where(metric_successful_subquery.c.last_successful_job_no == Job.job_no)),  # No reference in Metric
                    not_(exists().where(metric_subquery.c.last_job_no == Job.job_no)),
                    not_(exists().where(job_am_report_subquery.c.job_no == Job.job_no))  # No reference in JobAmReport
                )
            ).all()

        # print(f"Job nos to delete: {job_nos}")
        # logging.info(f"Job nos to delete: {job_nos}")

        # Delete the jobs based on the fetched IDs
        if job_nos:
            session.query(Job).filter(Job.job_no.in_([id[0] for id in job_nos])).delete(synchronize_session=False) # This setting tells SQLAlchemy to perform the delete operation directly in the database and not to bother updating the state of the session. This is faster and less resource-intensive if you know you won’t be using the session further or if you handle session consistency manually.

        session.commit()