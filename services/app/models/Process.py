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
from MessageLogger import setup_logger
import traceback
from concurrent.futures import ThreadPoolExecutor
import time
from models.users import User

from models.messages.sent import MessageSent, MessageForward
from models.messages.received import MessageSelection
from sqlalchemy.types import Enum as SQLEnum
from extensions import redis_client

class BaseProcess:
    def __init__(self, name):
        self.name = name

    def execute(self, message):
        raise NotImplementedError("This method should be implemented by subclasses")

    def save_state(self, job_id, state):
        key = f"job:{job_id}:state"
        redis_client.set(key, json.dumps(state))
        print(f"State saved for job {job_id}: {state}")

class DataCleaningProcess(BaseProcess):
    def execute(self, message):
        result = {
            "user_id": message['user_id'],
            "process": self.name,
            "result": f"Data cleaning process executed with message: {message}"
        }
        print(result)
        return result

class DataTransformationProcess(BaseProcess):
    def execute(self, message):
        result = {
            "user_id": message['user_id'],
            "process": self.name,
            "result": f"Data transformation process executed with message: {message}"
        }
        print(result)
        return result

class ModelTrainingProcess(BaseProcess):
    def execute(self, message):
        result = {
            "user_id": message['user_id'],
            "process": self.name,
            "result": f"Model training process executed with message: {message}"
        }
        print(result)
        return result
    