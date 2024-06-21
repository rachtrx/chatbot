
from extensions import Session, twilio

import os

from models.messages.MessageKnown import MessageKnown
from models.messages.MessageUnknown import MessageUnknown
from models.jobs.base.constants import OutgoingMessageData, MessageType, ErrorMessage
from models.messages.SentMessageStatus import SentMessageStatus

class AzureSyncError(Exception):
    def __init__(self, message):
        super().__init__(message)

class UserNotFoundError(Exception):
    def __init__(self, sid, incoming_body, user_no):
        self.sid = sid
        self.incoming_body = incoming_body
        self.user_no = user_no
        self.body = ErrorMessage.USER_NOT_FOUND

    def execute(self):
        session = Session()
        incoming_msg = MessageUnknown(sid=self.sid, user_no=self.user_no, body=self.incoming_body)
        session.add(incoming_msg)
        session.commit()

        sent_message_meta = twilio.messages.create(
            to=self.user_no,
            from_=os.environ.get('TWILIO_NO'),
            body=self.body
        )

        outgoing_msg = MessageUnknown(sid=sent_message_meta.sid, user_no=self.user_no, body=self.body)
        sent_msg_status = SentMessageStatus(sid=sent_message_meta.sid)
        session.add(outgoing_msg)
        session.add(sent_msg_status)
        session.commit()

        return
    
class EnqueueMessageError(Exception):
    def __init__(self, sid, incoming_body, user_id, body):
        self.sid = sid
        self.incoming_body = incoming_body
        self.user_id = user_id
        self.body = body

    def execute(self):

        from models.users import User

        session = Session()
        user = session.query(User).get(self.user_id)

        incoming_msg = MessageKnown(
            sid=self.sid, 
            msg_type=MessageType.RECEIVED,
            body=self.incoming_body,
            user_id=self.user_id
        )
        session.add(incoming_msg)
        session.commit()

        message = OutgoingMessageData(
            msg_type=MessageType.SENT,
            user=user,
            job_no=None,
            body=self.body
        )
        MessageKnown.send_msg(message)

        return

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, body, user_id, job_no, error=None):
        self.body = body
        self.user_id = user_id
        self.job_no = job_no
        self.error = error

    def execute(self):
        
        from models.users import User

        session = Session()
        user = session.query(User).get(self.user_id)

        reply_message = OutgoingMessageData(
            msg_type=MessageType.SENT,
            user=user,
            job_no=job.job_no,
            body=self.body
        )
        MessageKnown.send_msg(reply_message)

        if self.error:
            from models.jobs.base.Job import Job
            job = session.query(Job).get(self.job_no)
            job.error = self.error # ensure the column exists

        session.commit()

        return
