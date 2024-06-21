from flask import Flask
from extensions import Session
from config import Config

# TABLES

from models.users import User

from models.jobs.base.Job import Job
from models.jobs.base.Task import Task

from models.jobs.leave.Job import JobLeave
from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.tasks import ApproveLeave, CancelLeave, ExtractDates, RejectLeave, RequestAuthorisation, RequestConfirmation

from models.jobs.daemon.Job import JobDaemon
from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.tasks import AcquireToken, SendReport, SyncLeaves, SyncUsers

from models.messages.ForwardCallback import ForwardCallback
from models.messages.Message import Message
from models.messages.MessageKnown import MessageKnown
from models.messages.MessageUnknown import MessageUnknown
from models.messages.SentMessageStatus import SentMessageStatus

# SETUP REQUIREMENTS

from models.jobs.daemon.constants import DaemonTaskType
from models.jobs.base.Job import Job
from models.jobs.base.constants import JobType

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    with app.app_context():
        setup_azure()
        # setup_es()

    return app

def setup_azure():
    from routing.Scheduler import job_scheduler

    session = Session()

    try:
        job_no = Job.create_job(JobType.DAEMON, session)
        tasks_to_run = [DaemonTaskType.ACQUIRE_TOKEN, DaemonTaskType.SYNC_USERS, DaemonTaskType.SYNC_LEAVES]
        job_scheduler.add_to_queue(job_no, payload=tasks_to_run, session=session)
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        Session.remove()

def setup_es():
    # create_new_index()
    # loop_files()
    pass