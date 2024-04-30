from flask import Flask
from extensions import db, init_thread_session
from config import Config, twilio_client
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

from cryptography.fernet import Fernet
import hashlib
import os
from redis_client import Redis

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Bind extensions to the app
    db.init_app(app)

    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI']) # set echo = True if want to debug
    init_thread_session(engine)

    # Fernet encryption key setup
    FERNET_KEY = os.getenv("FERNET_KEY")
    cipher_suite = Fernet(FERNET_KEY)

    # Redis client setup 
    redis_client = Redis(app.config['REDIS_URL'], cipher_suite)

    # Utility function setup
    def hash_identifier(identifier, salt=''):
        hasher = hashlib.sha256()
        hasher.update(f'{salt}{identifier}'.encode())
        return hasher.hexdigest()

    app.redis_client = redis_client
    app.twilio_client = twilio_client
    app.hash_identifier = hash_identifier

    return app