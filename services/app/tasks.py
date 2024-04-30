from dotenv import load_dotenv
env_path = f"/etc/environment"
load_dotenv(dotenv_path=env_path)

from manage import create_app
from models.jobs.system.abstract import JobSystem
from constants import MessageType, MetricStatus
from extensions import init_thread_session, get_session, remove_thread_session

from models.messages.sent import MessageSent
from models.exceptions import AzureSyncError
from utilities import current_sg_time, convert_utc_to_sg_tz
from constants import JobStatus, SystemOperation
from logs.config import setup_logger
import logging
import traceback
from sqlalchemy import create_engine
import os
import json
from models.metrics import Metric

def main(jobs_to_run=[]):

    send_message = False

    jobs = [SystemOperation.ACQUIRE_TOKEN, SystemOperation.SYNC_USERS, SystemOperation.SYNC_LEAVE_RECORDS, SystemOperation.AM_REPORT]

    if len(jobs_to_run) == 0:

        cur_datetime = current_sg_time()
        logging.info(cur_datetime)

        minute = cur_datetime.minute

        logging.info(f"{minute}, {cur_datetime.hour}")

        if minute % 15 == 0:
            jobs_to_run.append(SystemOperation.SYNC_LEAVE_RECORDS)
            jobs_to_run.append(SystemOperation.SYNC_USERS) # this should be more regular than acquire

            if minute % 30 == 0:
                jobs_to_run.append(SystemOperation.ACQUIRE_TOKEN)
            
        if minute == 0 and cur_datetime.hour == 9 and cur_datetime.weekday() not in [5, 6]: # bool
            send_message = True
            jobs_to_run.append(SystemOperation.AM_REPORT)

    if len(jobs_to_run) == 0:
        return

    app = create_app()
    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    init_thread_session(engine)
    session = get_session()

    main_job = JobSystem.create_job(SystemOperation.MAIN)
    main_job.background_tasks = []
    cv = {}

    if send_message: # Temporary
        JobSystem.delete_old_jobs()

    for i, operation in enumerate(jobs, 1):

        cv_index = 1 + (i - 1) * 3 # arithmetic progression
        
        if operation in jobs_to_run:

            with app.app_context():

                job = JobSystem.create_job(operation)

                try:
                    metric = Metric.get_metric(operation)
                    metric.set_metric_start()
                    job.main() # updated the operation statuses
                    if getattr(job, "forwards_seq_no", None):
                        main_job.background_tasks.append([job.check_message_forwarded, (job.forwards_seq_no, job.map_joboperation())])
                        
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

    if send_message:
        cv = json.dumps(cv)
        content_sid = os.environ.get('SEND_SYSTEM_TASKS_SID')
        MessageSent.send_msg(MessageType.SENT, (content_sid, cv), main_job)

    main_job.run_background_tasks()

    remove_thread_session()

    logging.info("Tasks complete")
            
if __name__ == "__main__":
    main()
