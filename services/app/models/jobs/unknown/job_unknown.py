from models.jobs.abstract import Job

from logs.config import setup_logger
from extensions import db

from constants import PENDING
from utilities import current_sg_time
import uuid

class JobUnknown(Job):

    logger = setup_logger('models.job')

    __tablename__ = 'job_unknown'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)
    # job_no = db.Column(db.String, primary_key=True)
    # type = db.Column(db.String(50))
    # status = db.Column(db.Integer(), nullable=False)
    # created_at = db.Column(db.DateTime(timezone=True), default=current_sg_time())

    from_no = db.Column(db.String(30), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_unknown",
    }

    def __init__(self, from_no):
        super().__init__()
        self.from_no = from_no
        db.session.add(self)
        db.session.commit()