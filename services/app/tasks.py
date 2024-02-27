from manage import create_app
from constants import system
from models.jobs.system.abstract import JobSystem
from constants import messages

from dotenv import load_dotenv
from models.messages.sent import MessageSent
from utilities import current_sg_time
from constants import OK, FAILED
from logs.config import setup_logger

env_path = "/home/app/web/.env"
load_dotenv(dotenv_path=env_path)

def main(jobs=None):

    logger = setup_logger('system_tasks')

    daily_update_time = False

    if not jobs:

        cur_datetime = current_sg_time()

        jobs = []

        minute = cur_datetime.minute

        logger.info(f"{minute}, {cur_datetime.hour}")

        if minute == 0 and cur_datetime.hour == 8: # bool
            daily_update_time = True
            jobs.append(system["AM_REPORT"])

        if minute % 5 == 0:
            jobs.append(system["SYNC_USERS"]) # this should be more regular than acquire
            
            if minute % 30 == 0:
                jobs.append(system["ACQUIRE_TOKEN"])

                if minute == 0 and cur_datetime.hour == 8 and cur_datetime.weekday not in [5, 6]: # bool
                    daily_update_time = True
                    jobs.append(system["AM_REPORT"])

    if not jobs:
        return

    app = create_app()

    for job in jobs:

        logger.info(f"Creating job for {job}")

        with app.app_context():
            new_job = JobSystem.create_job(job)
            body = new_job.main()

            if new_job.task_status == OK and not daily_update_time:
                new_job.commit_status(OK)
                continue
            if new_job.task_status == FAILED:
                new_job.commit_status(FAILED)
            
            MessageSent.send_msg(messages['SENT'], body, new_job)
    
        
if __name__ == "__main__":
    main()
