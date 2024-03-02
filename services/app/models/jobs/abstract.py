from extensions import db
# from sqlalchemy.orm import 
import uuid
import logging
from constants import PENDING, OK, FAILED, messages, PENDING_USER_REPLY, PENDING_CALLBACK
import uuid
from utilities import current_sg_time, run_new_context, join_with_commas_and, get_session
import json
import os

from logs.config import setup_logger
import threading
import traceback

class Job(db.Model): # system jobs

    logger = setup_logger('models.job')

    __tablename__ = 'job'

    job_no = db.Column(db.String, primary_key=True)
    type = db.Column(db.String(50))
    status = db.Column(db.Integer(), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=current_sg_time())
    locked = db.Column(db.Boolean(), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job",
        "polymorphic_on": "type"
    }

    def __init__(self):
        print(f"current time: {current_sg_time()}")
        self.job_no = uuid.uuid4().hex
        self.created_at = current_sg_time()
        self.status = PENDING
        self.locked = False

    def unlock(self, session):
        self.locked = False
        session.commit()

    def lock(self, session):
        self.locked = True
        session.commit()

    def all_messages_successful(self):
        '''also checks for presence of the other confirm option'''

        session = get_session()

        session.refresh(self)

        all_msgs = self.messages

        all_replied = True

        for i, msg in enumerate(all_msgs):
            # self.logger.info("looping msgs in all_messages_successful")
            if msg.type == "message_confirm": # TODO maybe can just use type instead
                other_msg = msg.check_for_other_decision()
                if not other_msg:
                    self.logger.info("2 CONFIRMS NOT FOUND")
                if other_msg and (other_msg.status == OK or msg.status == OK): # what if both ok but its the return message
                    continue
                elif msg.status == FAILED: # TODO decide on whether to check for NOT OK instead!
                    all_replied = False
                    break
            else:
                if msg.status == FAILED: # TODO decide on whether to check for NOT OK instead!
                    all_replied = False
                    break
            self.logger.info(f"Message {i+1}: {msg.body}, status={msg.status}")

        if all_replied == True and self.status < 400:
            return True
        return False

    # to implement
    def validate_complete(self):
        pass

    def check_for_complete(self):
        session = get_session()
        if self.status == OK:
            return
        complete = self.validate_complete()
        self.logger.info(f"complete: {complete}")
        if complete:
            self.commit_status(OK)
        session.commit()

    def commit_status(self, status):
        '''tries to update status'''

        session = get_session()

        if status is None:
            return
        
        self.status = status

        from .user.abstract import JobUser

        if isinstance(self, JobUser) and not self.get_recent_pending_job(self.user.number):
            if (status == OK or status >= 400):
                self.user.is_blocking = False

            else: # PENDING. maybe expecting reply?
                self.user.is_blocking = True
        
        session.commit()

        self.logger.info(f"job status: {status}")

        return True

    def forward_status_not_null(self):
        if self.forwards_status == None:
            return False
        return True
    
    @run_new_context(wait_time=5)
    def check_message_forwarded(self, seq_no):

        session = get_session()
        logging.info(f"session id in check_message_forwarded: {id(session)}")

        for instance in session.identity_map.values():
            logging.info(f"Instance in check_message_forwarded session: {instance}")

        try:

            logging.basicConfig(
                filename='/var/log/app.log',  # Log file path
                filemode='a',  # Append mode
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
                level=logging.INFO  # Log level
            )
            logging.info("in threading function")

            from models.messages.sent import MessageForward

            forwarded_msgs = session.query(MessageForward).filter(
                MessageForward.job_no == self.job_no,
                MessageForward.seq_no == seq_no,
            )

            logging.info([f_msg.forward_status, f_msg.sid] for f_msg in forwarded_msgs)

            success = []
            failed = []
            unknown = []
            for f_msg in forwarded_msgs:
                to_name = f_msg.to_name

                if f_msg.status == OK:
                    success.append(to_name)
                elif f_msg.status == FAILED:
                    failed.append(to_name)
                else:
                    unknown.append(to_name)

            content_variables = {
                '1': join_with_commas_and(success) if len(success) > 0 else "NA",
                '2': join_with_commas_and(failed) if len(failed) > 0 else "NA",
                '3': join_with_commas_and(unknown) if len(unknown) > 0 else "NA"
            }
            
            content_variables = json.dumps(content_variables)

            reply = (os.environ.get("FORWARD_MESSAGES_CALLBACK_SID"), content_variables)

            MessageForward.send_msg(messages['SENT'], reply, self)

            if not len(failed) > 0 and not len(unknown) > 0: 
                self.forwards_status = OK
            elif len(unknown) > 0:
                self.forwards_status = PENDING
            else:
                self.forwards_status = FAILED
        except Exception as e:
            raise


    def update_with_msg_callback(self, status, sid, message):

        from models.messages.abstract import Message
        
        if (message.status != PENDING_CALLBACK):
            logging.info("message was not expecting a reply")
            return
        
        if status == "sent" and message.body is None:
            outgoing_body = Message.fetch_message(sid)
            logging.info(f"outgoing message: {outgoing_body}")
            message.commit_message_body(outgoing_body)

        elif status == "delivered":
            logging.info(f"message {sid} was sent successfully")

            if message.is_expecting_reply == True:
                self.commit_status(PENDING_USER_REPLY)
            
            message.commit_status(OK)
            
            if message.type == "message_forward":
                if self.forward_status_not_null():
                    self.check_message_forwarded(message.seq_no)
            
            # reply message expecting user reply. just to be safe, specify the 2 types of messages
        
        elif status == "failed":
            # job immediately fails
            if message.type == "message_forward" and self.forward_status_not_null():
                self.check_message_forwarded(message.seq_no)
            else:
                self.commit_status(FAILED) # forward message failed is still ok to some extent, especially if the user cancels afterwards. It's better to inform about the cancel

            message.commit_status(FAILED)

            if self.type == "job_es": # TODO should probably send to myself
                Message.send_msg(messages['SENT'], (os.environ.get("ERROR_SID"), None), self)
