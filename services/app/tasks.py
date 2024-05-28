from dotenv import load_dotenv
env_path = f"/etc/environment"
load_dotenv(dotenv_path=env_path)

from manage import create_app
from models.jobs.system.abstract import JobSystem
from constants import MessageType
from extensions import init_thread_session, remove_thread_session

from models.messages.sent import MessageSent
from models.exceptions import AzureSyncError
from utilities import current_sg_time
from constants import JobStatus, SystemOperation
from MessageLogger import setup_logger
import logging
import traceback
from sqlalchemy import create_engine
import os
import json

def main(jobs_to_run=[]):

    send_message = False

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

    with app.app_context():
        main_job = JobSystem.create_job(SystemOperation.MAIN)
        main_job.background_tasks = []
        
        cv = main_job.run_jobs(jobs_to_run)

    if send_message:
        cv = json.dumps(cv)
        content_sid = os.environ.get('SEND_SYSTEM_TASKS_SID')
        MessageSent.send_msg(MessageType.SENT, (content_sid, cv), main_job)

    main_job.run_background_tasks()

    remove_thread_session()

    logging.info("Tasks complete")
            
if __name__ == "__main__":
    main()
