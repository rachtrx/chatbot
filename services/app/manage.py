from flask import Flask
from extensions import db, init_thread_session
from sqlalchemy import create_engine

from models.users import User
from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageReceived, MessageSelection
from models.messages.abstract import Message

from models.jobs.abstract import Job
from models.jobs.system.abstract import JobSystem
from models.jobs.system.acq_token import JobAcqToken
from models.jobs.system.am_report import JobAmReport
from models.jobs.system.sync_users import JobSyncUsers
from models.jobs.system.sync_leave_records import JobSyncRecords
from models.jobs.user.abstract import JobUserInitial
from models.jobs.user.leave.main import JobLeave
from models.jobs.user.es import JobEs
from models.leave_records import LeaveRecord
from models.metrics import Metric

from config import Config

from models.jobs.daemon.constants import DaemonTaskType

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    with app.app_context():
        setup_azure()
        # setup_es()

    # Bind extensions to the app
    db.init_app(app)

    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI']) # set echo = True if want to debug
    init_thread_session(engine)

    return app

def setup_azure():
    return [DaemonTaskType.ACQUIRE_TOKEN, DaemonTaskType.SYNC_USERS, DaemonTaskType.SYNC_LEAVES]

def setup_es():
    # create_new_index()
    # loop_files()
    pass