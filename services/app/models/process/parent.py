from extensions import db, get_session, remove_thread_session
from sqlalchemy import inspect
import shortuuid
import logging
from constants import MessageType, Error, JobStatus, SentMessageStatus, SystemOperation, Intent, ForwardStatus
from utilities import current_sg_time, join_with_commas_and, log_instances, run_new_context
import json
import os
import threading
from datetime import datetime, timedelta
from models.users import User
from datetime import datetime, timedelta
import logging

from models.exceptions import ReplyError
from MessageLoggersetup_logger
import traceback
from concurrent.futures import ThreadPoolExecutor
import time
from models.users import User

from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageSelection
from sqlalchemy.types import Enum as SQLEnum

class ParentProcess(db.Model): # system jobs

    __abstract__ = True
    logger = setup_logger('models.job')

    status = db.Column(SQLEnum(JobStatus), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True))
    locked = db.Column(db.Boolean(), nullable=False)
    name = db.Column(db.String(80), nullable=True)
    