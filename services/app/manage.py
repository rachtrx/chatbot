import traceback
from flask import Flask
from config import Config

# TABLES

# from models.users import User

# from models.jobs.base.Job import Job
# from models.jobs.base.Task import Task

# from models.jobs.leave.Job import JobLeave
# from models.jobs.leave.Task import TaskLeave
# from models.jobs.leave.LeaveRecord import LeaveRecord
# from models.jobs.leave.tasks import CancelLeave, ExtractDates, ConfirmLeave

# from models.jobs.daemon.Job import JobDaemon
# from models.jobs.daemon.Task import TaskDaemon
# from models.jobs.daemon.tasks import AcquireToken, SendReport, SyncLeaves, SyncUsers

# from models.messages.ForwardCallback import ForwardCallback
# from models.messages.Message import Message
# from models.messages.MessageKnown import MessageKnown
# from models.messages.MessageUnknown import MessageUnknown
# from models.messages.SentMessageStatus import SentMessageStatus
# from services.app.models.jobs.leave.tasks import ConfirmLeave

def create_app():
    print("create_app called from:", traceback.format_stack(limit=2)[-2])
    app = Flask(__name__)
    app.config.from_object(Config)

    return app