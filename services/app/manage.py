from flask import Flask, has_request_context
from extensions import db
from config import Config

from models.users import User
from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageReceived, MessageConfirm
from models.messages.abstract import Message

from models.jobs.abstract import Job
from models.jobs.system.abstract import JobSystem
from models.jobs.system.acq_token import JobAcqToken
from models.jobs.system.am_report import JobAmReport
from models.jobs.system.sync_users import JobSyncUsers
from models.jobs.user.abstract import JobUser
from models.jobs.user.mc import JobMc
from models.jobs.user.es import JobEs
from models.mc_records import McRecord
# from models.metrics import Metric

from sqlalchemy.orm import scoped_session, sessionmaker

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    return app