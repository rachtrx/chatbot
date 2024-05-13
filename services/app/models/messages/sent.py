from extensions import db, get_session
from constants import MessageType, SentMessageStatus, SelectionType, types_to_selections
import os
import json
from config import twilio_client
from .abstract import Message
import time
import logging
import traceback

from utilities import join_with_commas_and, print_all_dates

from models.users import User
from models.exceptions import ReplyError

from logs.config import setup_logger
from sqlalchemy.types import Enum as SQLEnum


# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class MessageSent(Message):

    logger = setup_logger('models.message_sent')
    __tablename__ = "message_sent"

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    selection_type = db.Column(SQLEnum(SelectionType), nullable=True)
    status = db.Column(SQLEnum(SentMessageStatus), nullable=False)
    
    # job = db.relationship('Job', backref='sent_messages', lazy='select')

    __mapper_args__ = {
        "polymorphic_identity": "message_sent",
    }

    def __init__(self, job_no, sid, selection_type, seq_no=None, body=None):
        super().__init__(job_no, sid, body, seq_no) # initialise message
        self.status = SentMessageStatus.PROCESSING
        self.selection_type = selection_type

    def get_selection_type(self):
        return types_to_selections[self.selection_type]

    def commit_message_body(self, body):
        session = get_session()
        self.body = body
        self.logger.info(f"message body committed: {self.body}")
        session.commit()

    def commit_status(self, status):
        self.logger.info(f"trying to commit status {status}")
        session = get_session()
        '''tries to update status'''
        self.status = status
        session.commit()
        self.logger.info(f"message committed with status {status}")

        message = session.query(MessageSent).filter_by(sid=self.sid).first()
        self.logger.info(f"message status: {message.status}, passed status: {status}")
        return True

    @classmethod
    def send_msg(cls, msg_type, reply, job, **kwargs): 

        '''kwargs supplies the init variables to Message.create_messages() which call the following init functions based on the msg_type: 
        
        msg_type == MessageType.SENT:
        MessageSent.__init__(self, job_no, sid, selection_type, seq_no=None, body=None): 

        msg_type == MessageType.FORWARD:
        MessageForward.__init__(self, job_no, sid, selection_type, seq_no, to_name):

        job_no, sid, and selection_type are updated; the rest has to be passed as kwargs.

        For MessageSent, additional kwargs is not required (min total 3 args)
        For MessageForward, additional kwargs is required for seq_no and relation (min total 5 args)

        for template messages, sid and cv are passed through reply as a tuple
        '''

        # kwargs["selection_type"] sets the MessageSent.selection_type col. job.selection_type is used to save into cache later on and not needed to be stored in JobUser or ReceivedMessage table...
        if msg_type == MessageType.FORWARD:
            to_no = kwargs['to_user'].sg_number # forward message
            kwargs["selection_type"] = getattr(job, 'selection_type', False)
        else: # SENT
            from models.jobs.user.abstract import JobUser
            from models.jobs.unknown.unknown import JobUnknown
            from models.jobs.system.abstract import JobSystem
            if isinstance(job, JobUnknown):
                to_no = job.from_no # unknown number
            elif isinstance(job, JobUser):
                to_no = job.user.sg_number # user number
            elif isinstance(job, JobSystem):
                to_no = job.root_user.sg_number # user number
            kwargs["selection_type"] = getattr(job, 'selection_type', False)

        # Send the message
        if isinstance(reply, tuple):
            sid, cv = reply
            logging.info(cv)
            sent_message_meta = cls._send_template_msg(sid, cv, to_no)
        else:
            sent_message_meta = cls._send_normal_msg(reply, to_no)

        kwargs["job_no"] = job.job_no
        kwargs["sid"] = sent_message_meta.sid

        sent_msg = Message.create_message(msg_type, **kwargs)

        sent_msg.commit_status(SentMessageStatus.PENDING_CALLBACK)
        return sent_msg

    @staticmethod
    def _send_template_msg(content_sid, content_variables, to_no):

        logging.info(content_variables)

        sent_message_meta = twilio_client.messages.create(
                to=to_no,
                from_=os.environ.get("MESSAGING_SERVICE_SID"),
                content_sid=content_sid,
                content_variables=content_variables if content_variables is not None else {}
            )

        return sent_message_meta

    @staticmethod
    def _send_normal_msg(body, to_no):
        '''so far unused'''
        sent_message_meta = twilio_client.messages.create(
            from_=os.environ.get("TWILIO_NO"),
            to=to_no,
            body=body
        )
        return sent_message_meta
    
    @staticmethod
    def _send_error_msg(body="Something went wrong with the sync"):
        sent_message_meta = twilio_client.messages.create(
            from_=os.environ.get("TWILIO_NO"),
            to=os.environ.get("DEV_NO"),
            body=body
        )
        return sent_message_meta
    
class MessageForward(MessageSent):

    logger = setup_logger('models.message_forward')

    #TODO other statuses eg. wrong duration

    __tablename__ = "message_forward"
    sid = db.Column(db.ForeignKey("message_sent.sid"), primary_key=True)
    to_name = db.Column(db.String(80), nullable=False)
    # forward_status = db.Column(db.Integer(), nullable=False)
    # message_pending_forward = db.Column(db.ForeignKey("message.sid"))

    # unused
    @property
    def to_user(self):
        if not getattr(self, '_to_user', None):
            session = get_session()
            self.to_user = session.query(User).filter_by(name=self.to_name).first()
        return self._to_user
    
    @to_user.setter
    def to_user(self, value):
        self._to_user = value

    __mapper_args__ = {
        "polymorphic_identity": "message_forward",
        'inherit_condition': sid == MessageSent.sid
    }

    def __init__(self, job_no, sid, selection_type, seq_no, to_user):
        self.logger.info(f"forward message created for {to_user.name}")
        super().__init__(job_no, sid, selection_type, seq_no) # initialise message, body is always none since need templates to forward
        self.to_name = to_user.name
    
    @staticmethod
    def acknowledge_selection():
        return f"All messages have been sent successfully."

    ########################
    # CHATBOT FUNCTIONALITY
    ########################
    
    @classmethod
    def forward_template_msges(cls, job):
        '''Ensure the job has the following attributes: cv_and_users_list, content_sid (only needed for forward messages). It sets successful_forwards and forwards_seq_no'''

        job.forwards_seq_no = MessageSent.get_seq_no(job.job_no) + 1
        job.successful_forwards = []

        for content_variables, to_user in job.cv_and_users_list:
            try:
                cls.send_msg(
                    msg_type=MessageType.FORWARD,
                    reply=(job.content_sid, content_variables), 
                    job=job, 
                    seq_no=job.forwards_seq_no,
                    to_user=to_user
                )
                job.successful_forwards.append(to_user.name)
            except Exception:
                cls.logger.error(traceback.format_exc())
                continue

    #################################
    # CV TEMPLATES FOR MANY MESSAGES
    #################################
    
    

