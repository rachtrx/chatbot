from models.jobs.abstract import Job
from datetime import timedelta

from logs.config import setup_logger
from extensions import db
from models.exceptions import ReplyError

from constants import PROCESSING
from utilities import get_session, current_sg_time

class JobUnknown(Job):

    logger = setup_logger('models.job')

    __tablename__ = 'job_unknown'

    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True)

    from_no = db.Column(db.String(30), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_unknown",
    }

    def __init__(self, from_no):
        super().__init__()
        self.from_no = from_no
        db.session.add(self)
        db.session.commit()

    @classmethod
    def check_for_prev_job(cls, from_no):
        session = get_session()
        last_job = session.query(cls).filter_by(from_no=from_no).first()

        if last_job and current_sg_time() - last_job.created_at <= timedelta(hours=1):
            return True
        
        else:
            return False

        