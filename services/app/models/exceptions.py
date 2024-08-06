
from extensions import Session, twilio

import os
import traceback
import logging

from twilio.base.exceptions import TwilioRestException

from MessageLogger import setup_logger

from models.jobs.base.constants import OutgoingMessageData, MessageType, MESSAGING_SERVICE_SID
from models.jobs.base.utilities import clear_user_processing_state

from models.messages.MessageKnown import MessageKnown
from models.messages.MessageUnknown import MessageUnknown
from models.messages.SentMessageStatus import SentMessageStatus

class AzureSyncError(Exception):
    def __init__(self, message):
        super().__init__(message)

class NoRelationsError(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        self.message = message

class DaemonTaskError(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        self.message = message

class UserNotFoundError(Exception):
    def __init__(self, user_no):
        self.user_no = user_no

    def execute(self):
        session = Session()

        sent_message_meta = twilio.messages.create(
            to=self.user_no,
            from_=MESSAGING_SERVICE_SID,
            content_sid=os.getenv('USER_NOT_FOUND_ERROR_SID'),
        )

        outgoing_msg = MessageUnknown(user_no=self.user_no, sid=sent_message_meta.sid, msg_type=MessageType.SENT) # let body be none since sometimes non user may be outside the 24 hour window too
        sent_msg_status = SentMessageStatus(sid=sent_message_meta.sid)
        session.add(outgoing_msg)
        session.add(sent_msg_status)
        session.commit()
        return
    
class EnqueueMessageError(Exception):
    def __init__(self, sid, user_id, incoming_body, body):
        self.sid = sid
        self.incoming_body = incoming_body
        self.user_id = user_id
        self.body = body

    def execute(self):

        session = Session()

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
            user_id=self.user_id,
            job_no=None,
            body=self.body
        )
        MessageKnown.send_msg(message)

        return

class ReplyError(Exception):
    """throws error when trying to reply but message not found"""

    def __init__(self, message: OutgoingMessageData, error=None):
        self.message = message
        self.error = error
        self.logger = setup_logger(f'replyerror')

    def execute(self):

        self.logger.info("Running Error handling in ReplyError")

        session = Session()
        
        new_err_message = None
        try:
            if self.error and self.message.job_no:
                from models.jobs.base.Job import Job
                job = session.query(Job).get(self.message.job_no)
                job.handle_error(self.message, self.error)
            else:
                self.logger.info(f"Sending non job error err_message: {self.message}")
                MessageKnown.send_msg(self.message)

        except TwilioRestException:
            self.logger.error(traceback.format_exc())
            new_err_message = "Failed to forward any messages. You may have to inform relevant staff manually"
        except Exception:
            self.logger.error("New error caught")
            self.logger.error(traceback.format_exc())
            new_err_message = "Another unknown error was caught when handling the error. You may have to inform relevant staff manually"
        
        finally:
            if new_err_message:
                new_message = OutgoingMessageData(
                    job_no=self.message.job_no,
                    user_id=self.message.user_id,
                    body=new_err_message
                )
                MessageKnown.send_msg(new_message)

            clear_user_processing_state(self.message.user_id)
            session.commit()

        return
