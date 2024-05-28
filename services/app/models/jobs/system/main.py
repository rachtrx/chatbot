from extensions import db
from .abstract import Job
from MessageLogger import setup_logger
import os
import msal
from azure.utils import generate_header
import requests
import traceback
from utilities import get_session, convert_utc_to_sg_tz
from datetime import datetime
import json
import logging
from models.exceptions import AzureSyncError
from constants import SystemOperation, JobStatus, MetricStatus
from models.metrics import Metric
from sqlalchemy import not_, exists, and_
import logging

class JobSystemMain(Job):

    logger = setup_logger('az.acq_token')

    __tablename__ = 'job_system_main'
    job_no = db.Column(db.ForeignKey("job_system.job_no", ondelete='CASCADE'), primary_key=True)

    __mapper_args__ = {
        "polymorphic_identity": SystemOperation.MAIN
    }

    def __init__(self, jobs):
        self.jobs = jobs
        self.background_tasks = []

    def run_jobs(self):
        session = get_session()

        cv = {}

        if send_message: # Temporary
            self.delete_old_jobs()

        for i, operation in enumerate(SystemOperation.__dict__.keys(), 1):

            cv_index = 1 + (i - 1) * 3 # arithmetic progression
            
            if operation in self.jobs:

                job = Job.create_job(operation)

                try:
                    metric = Metric.get_metric(operation)
                    metric.set_metric_start()
                    job.main() # updated the operation statuses
                    if getattr(job, "forwards_seq_no", None):
                        self.background_tasks.append([job.update_user_on_forwards, (job.forwards_seq_no, job.map_job_type())])
                        
                    logging.info(f"JOB FINISHED WITH REPLY {job.reply} and STATUS {job.status}")

                    if job.error == True:
                        job.commit_status(JobStatus.SERVER_ERROR)
                    elif job.status != JobStatus.SERVER_ERROR:
                        logging.info("JOB WAS SUCCESSFUL")
                        job.commit_status(JobStatus.OK)

                    cv[str(cv_index)] = job.reply

                except AzureSyncError as e:
                    logging.error(traceback.format_exc())
                    session.rollback()
                    job.commit_status(JobStatus.SERVER_ERROR)
                    cv[str(cv_index)] = f"Failed: {e.message}"

                except Exception as e:
                    logging.error(traceback.format_exc())
                    session.rollback()
                    job.commit_status(JobStatus.SERVER_ERROR)
                    cv[str(cv_index)] = "Failed (Unknown Error)"
                
                send_message = metric.set_metric_status(job) or send_message
            else:
                metric = Metric.get_metric(operation)
                if metric.status == MetricStatus.OK:
                    cv[str(cv_index)] = "Success" 
                elif metric.status == None:
                    cv[str(cv_index)] = "Unknown"
                else:
                    cv[str(cv_index)] = "Failed"

            try:
                last_update = getattr(metric, 'last_update', None)
                if not last_update:
                    cv[str(cv_index + 1)] = "NIL"
                else:
                    cv[str(cv_index + 1)] = convert_utc_to_sg_tz(metric.last_update, '%d-%m-%Y %H:%M:%S')

                last_successful_update = getattr(metric, 'last_successful_update', None)
                if not last_successful_update:
                    cv[str(cv_index + 2)] = "NIL"
                else:
                    cv[str(cv_index + 2)] = convert_utc_to_sg_tz(metric.last_successful_update, '%d-%m-%Y %H:%M:%S')
            except Exception as e:
                session.rollback()
                logging.error(traceback.format_exc())
                cv[str(cv_index + 1)] = "Failed (Unknown Error)"
                cv[str(cv_index + 2)] = "Failed (Unknown Error)"
        return cv


    @classmethod
    def delete_old_jobs(cls):
        '''method used on SystemOperation Jobs only!'''
        from models.messages.abstract import Message
        from models.metrics import Metric
        from .system.am_report import JobAmReport
        session = get_session()
        threshold = datetime.now() - timedelta(days=180)  # temporary

        # Subqueries for checking references
        message_subquery = session.query(Message.job_no).filter(Message.job_no == Job.job_no).subquery()
        metric_successful_subquery = session.query(Metric.last_successful_job_no).filter(Metric.last_successful_job_no == Job.job_no).subquery()
        metric_subquery = session.query(Metric.last_job_no).filter(Metric.last_job_no == Job.job_no).subquery()
        job_am_report_subquery = session.query(JobAmReport.job_no).filter(JobAmReport.job_no == Job.job_no).subquery()

        job_nos = session.query(Job.job_no).\
            filter(
                and_(
                    Job.created_at < threshold,
                    isinstance(Job.type, SystemOperation),
                    not_(exists().where(message_subquery.c.job_no == Job.job_no)),  # No reference in Message
                    not_(exists().where(metric_successful_subquery.c.last_successful_job_no == Job.job_no)),  # No reference in Metric
                    not_(exists().where(metric_subquery.c.last_job_no == Job.job_no)),
                    not_(exists().where(job_am_report_subquery.c.job_no == Job.job_no))  # No reference in JobAmReport
                )
            ).all()
        
        # Delete the jobs based on the fetched IDs
        if job_nos:
            session.query(Job).filter(Job.job_no.in_([id[0] for id in job_nos])).delete(synchronize_session=False) # This setting tells SQLAlchemy to perform the delete operation directly in the database and not to bother updating the state of the session. This is faster and less resource-intensive if you know you won’t be using the session further or if you handle session consistency manually.

        session.commit()


