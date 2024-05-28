from extensions import db, get_session
from models.jobs.abstract import Job
from MessageLogger import setup_logger
from constants import JobStatus, SystemOperation
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

    __mapper_args__ = {
        "polymorphic_identity": "job_system",
        "polymorphic_on": "type"
    }

    def __init__(self, name="ICT Hotline"):
        super().__init__()
        self.name = name
        self.status = JobStatus.PROCESSING