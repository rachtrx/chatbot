import os
import re
import traceback
import json
from twilio.base.exceptions import TwilioRestException

from extensions import db, get_session
from config import twilio

from models.jobs.base.constants import ErrorMessage, MessageOrigin, MessageType, JobType, OutgoingMessageData, leave_alt_words
from models.jobs.base.utilities import current_sg_time

from models.messages.SentMessageStatus import SentMessageStatus
from models.messages.ForwardCallback import ForwardCallback
from models.messages.MessageBase import MessageBase

class MessageKnown(MessageBase):

    # sid = db.Column(db.String(80), primary_key=True, nullable=False)
    # body = db.Column(db.String(), nullable=True)
    # timestamp = db.Column(db.DateTime(timezone=True), nullable=False)

    __tablename__ = 'message_known'

    seq_no = db.Column(db.Integer(), nullable=False)

    job_no = db.Column(db.String, db.ForeignKey('job.job_no'), nullable=True)
    job = db.relationship('Job', backref='messages', lazy='select')

    user_id = db.Column(db.ForeignKey("users.id"), nullable=False)
    user = db.relationship('User', backref='messages', lazy='select')

    __mapper_args__ = {
        "polymorphic_identity": MessageOrigin.KNOWN,
    }

    def __init__(self, sid, msg_type, body, user_id, job_no=None, seq_no=None):
        self.logger.info(f"current time: {current_sg_time()}")
        super().__init__(sid, body)
        self.msg_type = msg_type
        self.user_id = user_id
        self.job_no = job_no
        if seq_no is not None:
            self.seq_no = seq_no
        else:
            cur_seq_no = self.get_seq_no(job_no)
            self.seq_no = cur_seq_no + 1
        self.logger.info(f"new_message: {self.body}, seq no: {self.seq_no}")
    
    def get_intent(self):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''
        
        self.logger.info(f"message: {self.body}")
                
        leave_alt_words_pattern = re.compile(leave_alt_words, re.IGNORECASE)
        if leave_alt_words_pattern.search(self.body):
            return JobType.LEAVE
            
        # return Intent.ES_SEARCH
        return JobType.UNKNOWN
    
    # TO CHECK
    @staticmethod
    def get_seq_no(job_no):
        '''finds the sequence number of the message in the job, considering all message types'''

        session = get_session()
        for instance in session.identity_map.values():
            self.logger.info(f"Instance in get_seq_no session: {instance}")

        messages = session.query(Message).filter_by(job_no=job_no).all()

        if len(messages) > 0:
            # Then query the messages relationship
            cur_seq_no = max(message.seq_no for message in messages)
        else:
            cur_seq_no = 0

        return cur_seq_no
    
    @classmethod
    def get_message_by_sid(cls, sid):
        session = get_session()

        msg = session.query(cls).filter_by(
            sid=sid
        ).first()
        
        return msg if msg else None
    
    def commit_message_body(self, body):
        session = get_session()
        self.body = body
        self.logger.info(f"message body committed: {self.body}")
        session.commit()

    @classmethod
    def send_msg(cls, message: OutgoingMessageData, seq_no=None, serialised=False):

        from models.exceptions import ReplyError

        sent_message_meta = None

        if message.body:
            sent_message_meta = twilio.messages.create(
                from_=os.environ.get("TWILIO_NO"),
                to=message.to_no,
                body=message.body
            )
        else:
            if not message.content_variables:
                message.content_variables = {}
            elif not serialised:
                message.content_variables = json.dumps(message.content_variables)
            # else it is already serialised

            self.logger.info(message.content_variables)

            try:
                sent_message_meta = twilio.messages.create(
                    to=message.to_no,
                    from_=os.environ.get("MESSAGING_SERVICE_SID"),
                    content_sid=message.content_sid,
                    content_variables=message.content_variables
                )
            except TwilioRestException:
                raise ReplyError(body=ErrorMessage.TWILIO_ERROR, user_id=message.user.id, job_no=message.job_no)

        sent_msg = cls.__init__( # used init for code readability
            sid=sent_message_meta.sid,
            msg_type=message.msg_type, 
            body=message.body if message.body else None,
            job_no=message.job_no, 
            user_id=message.user.id, 
            seq_no=seq_no, 
            )
        
        sent_msg_status = SentMessageStatus(sid=sent_message_meta.sid)

        session = get_session()
        session.add(sent_msg)
        session.add(sent_msg_status)

    @classmethod
    def forward_template_msges(cls, job_no, sid_list, cv_list, users_list, user_id_to_update=None, callback=None, message_context=None):
        '''Ensure the callback accepts 2 arguments successful_aliases and forward_callback object'''

        cv_list = [json.dumps(cv) for cv in cv_list]

        seq_no = cls.get_seq_no(job_no) + 1
        successful_aliases = []

        for sid, content_variables, to_user in zip(sid_list, cv_list, users_list):
            try:
                message = OutgoingMessageData(
                    msg_type = MessageType.FORWARD,
                    user = to_user,
                    job_no = job_no,
                    content_sid=sid, # cannot be body, due to 24hr period of Twilio standards
                    content_variables=content_variables # TODO
                    )
                cls.send_msg(
                    message=message, seq_no=seq_no, serialised=True
                )
                successful_aliases.append(to_user.alias)
            except Exception:
                cls.logger.error(traceback.format_exc()) # TODO? 
                continue

        if user_id_to_update:
            session = get_session()
            forward_callback = ForwardCallback(job_no=job_no, seq_no=seq_no, user_id=user_id_to_update, message_context=message_context)
            session.add(forward_callback)
            session.commit()
        else:
            forward_callback = None

        if callback:
            callback(successful_aliases, forward_callback)


    def construct_forward_metadata(sid, cv_list, users_list):
        sid_list = None

        if isinstance(sid, list):
            sid_list = sid
        else:
            sid_list = [sid] * len(cv_list)

        return {
            'sid_list': sid_list,
            'cv_list': cv_list,
            'users_list': users_list
        }