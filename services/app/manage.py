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
from models.jobs.user.abstract import JobUser
from models.jobs.user.leave import JobLeave
from models.jobs.user.es import JobEs
from models.leave_records import LeaveRecord
from models.metrics import Metric

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Bind extensions to the app
    db.init_app(app)

    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI']) # set echo = True if want to debug
    init_thread_session(engine)

    return app