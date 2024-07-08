from extensions import db

import os
import msal
import requests
import traceback
from datetime import datetime

from models.jobs.base.utilities import current_sg_time
from models.jobs.base.constants import OutgoingMessageData, MessageType

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import DaemonTaskType, DaemonMessage
from models.jobs.daemon.utilities import generate_header

from models.messages.MessageKnown import MessageKnown

class SendHealth(TaskDaemon):

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SEND_HEALTH
    }

    def execute(self):
        message = OutgoingMessageData(
            msg_type=MessageType.SENT,
            user_id=self.user_id,
            job_no=self.job_no,
            content_sid=self.payload['sid'],
            content_variables=self.payload['cv']
        )
        MessageKnown.send_msg(message=message)