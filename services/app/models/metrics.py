import requests
from datetime import datetime
from extensions import db, get_session
# from sqlalchemy.orm import 
from sqlalchemy import ForeignKey
from logs.config import setup_logger
from constants import metric_names, OK, SERVER_ERROR, PROCESSING, METRIC_MAPPING
from utilities import current_sg_time
import logging

class Metric(db.Model):

    logger = setup_logger('models.metrics')

    __tablename__ = "metrics"
    
    _type = db.Column(db.String(30), primary_key=True, nullable=False)
    status = db.Column(db.Integer, nullable=True)
    last_update = db.Column(db.DateTime(timezone=True), default=None, nullable=True)
    last_successful_update = db.Column(db.DateTime(timezone=True), default=None, nullable=True)
    last_job_no = db.Column(db.ForeignKey("job.job_no"), nullable = True)
    last_successful_job_no = db.Column(db.ForeignKey("job.job_no"), nullable = True)

    def __init__(self, _type):
        session = get_session()
        self._type = _type
        session.add(self)
        session.commit()

    @classmethod
    def get_metric(cls, _type):
        session = get_session()
        metric = session.query(cls).filter_by(_type = METRIC_MAPPING[_type]).first()
        if not metric:
            metric = cls(METRIC_MAPPING[_type])
        return metric
    
    def set_metric_start(self):
        session = get_session()
        self.status = PROCESSING
        session.commit()

    def set_metric_status(self, job):
        cur_time = current_sg_time()

        session = get_session()
        updates_match = self.last_successful_update == self.last_update
        self.status = job.status

        if self.status == OK:
            self.last_successful_update = cur_time
            self.last_successful_job_no = job.job_no
        self.last_update = cur_time
        self.last_job_no = job.job_no
        session.commit()

        # both last update and last successful update are the same, and suddenly status not ok; or last update not last usccessful update but it didnt fail
        if updates_match and self.status != OK or not updates_match and self.status != SERVER_ERROR:
            return True
        
        return False

    def update_azure_status():
        pass