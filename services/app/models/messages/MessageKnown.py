import os
import re
import traceback
import json
from twilio.base.exceptions import TwilioRestException

from extensions import db, Session, twilio

from models.jobs.base.constants import Error, ErrorMessage, MessageOrigin, MessageType, JobType, OutgoingMessageData, \
    MESSAGING_SERVICE_SID, TWILIO_NO
from models.jobs.base.utilities import current_sg_time

from models.jobs.leave.constants import Patterns, LeaveError

from models.messages.Message import Message

class MessageKnown(Message):

    # sid = db.Column(db.String(80), primary_key=True, nullable=False)
    # body = db.Column(db.String(), nullable=True)
    # timestamp = db.Column(db.DateTime(timezone=True), nullable=False)

    __tablename__ = 'message_known'

    sid = db.Column(db.String, db.ForeignKey('message.sid'), primary_key=True, nullable=False)

    job_no = db.Column(db.String, db.ForeignKey('job.job_no'), nullable=True)
    job = db.relationship('Job', backref='messages', lazy='select')

    user_id = db.Column(db.ForeignKey("users.id"), nullable=False)
    user = db.relationship('User', backref='messages', lazy='select')

    seq_no = db.Column(db.Integer(), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": MessageOrigin.KNOWN,
    }

    def __init__(self, sid, msg_type, body, user_id, job_no=None, seq_no=None):
        self.logger.info(f"current time: {current_sg_time()}")
        super().__init__(sid, msg_type, body)
        self.user_id = user_id
        self.job_no = job_no
        if seq_no is not None:
            self.seq_no = seq_no
        else:
            cur_seq_no = self.get_seq_no(job_no)
            self.seq_no = cur_seq_no + 1
        self.logger.info(f"new_message: {self.body}, seq no: {self.seq_no}")

    @classmethod
    def get_intent(cls, body):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''
        
        cls.logger.info(f"message: {cls.body}")
                
        leave_alt_words_pattern = re.compile(Patterns.LEAVE_ALT_WORDS, re.IGNORECASE)
        if leave_alt_words_pattern.search(body):
            return JobType.LEAVE
            
        # return Intent.ES_SEARCH
        return JobType.UNKNOWN
    
    # TO CHECK
    @staticmethod
    def get_seq_no(job_no):
        '''finds the sequence number of the message in the job, considering all message types'''

        if job_no is None:
            return 0

        session = Session()

        messages = session.query(MessageKnown).filter_by(job_no=job_no).all()

        if len(messages) > 0:
            # Then query the messages relationship
            cur_seq_no = max(message.seq_no for message in messages)
        else:
            cur_seq_no = 0

        return cur_seq_no
    
    @classmethod
    def get_message_by_sid(cls, sid):
        session = Session()

        msg = session.query(cls).filter_by(
            sid=sid
        ).first()
        
        return msg if msg else None
    
    def commit_message_body(self, body):
        session = Session()
        self.body = body
        self.logger.info(f"message body committed: {self.body}")
        session.commit()

    @classmethod
    def send_msg(cls, message: OutgoingMessageData, seq_no=None):

        from models.exceptions import ReplyError
        from models.users import User

        to_user = Session().query(User).get(message.user_id)

        cls.logger.info(f"Current number: {to_user.number}")
        cls.logger.info(f"Active numbers: {json.loads(os.getenv('ACTIVE_NUMBERS'))}, Type: {type(json.loads(os.getenv('ACTIVE_NUMBERS')))}")

        if int(os.getenv('LIVE')) or int(to_user.number) in json.loads(os.getenv('ACTIVE_NUMBERS')):
            cls.logger.info("Current number in active numbers")
            to_no = to_user.sg_number
            cls.logger.info('Sending to Actual User')
        else:
            to_no = os.getenv('DEV_NO')
            cls.logger.info('Sending to Dev')

        sent_message_meta = None

        try:
            if message.body:
                cls.logger.info(f"to_user_no: {to_user.sg_number}")
                sent_message_meta = twilio.messages.create(
                    from_=TWILIO_NO,
                    to=to_no,
                    body=message.body
                )
            else:
                if message.content_variables:
                    if not all(isinstance(value, str) for value in message.content_variables.values()):
                        raise Exception
                    message.content_variables = json.dumps(message.content_variables)

                cls.logger.info(f"Message SID: {message.content_sid}")
                cls.logger.info(f"Message CV: {message.content_variables}")
                
                cls.logger.info(f"SANITY CHECK: MESSAGING_SERVICE_SID = {MESSAGING_SERVICE_SID}")
                sent_message_meta = twilio.messages.create(
                    to=to_no,
                    from_=MESSAGING_SERVICE_SID,
                    content_sid=message.content_sid,
                    content_variables=message.content_variables
                )

            sent_msg = cls(
                sid=sent_message_meta.sid,
                msg_type=message.msg_type,
                body=message.body if message.body else None,
                job_no=message.job_no, 
                user_id=message.user_id, 
                seq_no=seq_no, 
            )

            from models.messages.SentMessageStatus import SentMessageStatus
            sent_msg_status = SentMessageStatus(sid=sent_message_meta.sid)

            session = Session()
            session.add(sent_msg)
            session.add(sent_msg_status)
            session.commit()

        except TwilioRestException:
            message = OutgoingMessageData(
                body=ErrorMessage.TWILIO_ERROR, 
                user_id=message.user_id, 
                job_no=message.job_no
            )
            raise ReplyError(message, error=Error.UNKNOWN)

    @classmethod
    def forward_template_msges(cls, job_no, sid_list, cv_list, users_list, user_id_to_update=None, callback=None, message_context=None):
        '''Ensure the callback accepts 1 forward_callback object as the arg'''

        from models.exceptions import ReplyError
        
        if len(users_list) == 0:
            message = OutgoingMessageData(
                user_id=user_id_to_update,
                job_no=job_no,
                body=ErrorMessage.NO_FORWARD_MESSAGE_FOUND
            )
            raise ReplyError(message)

        seq_no = cls.get_seq_no(job_no) + 1
        successful_aliases = []

        for sid, content_variables, to_user in zip(sid_list, cv_list, users_list):
            try:
                message = OutgoingMessageData(
                    msg_type = MessageType.FORWARD,
                    user_id = to_user.id,
                    job_no = job_no,
                    content_sid=sid, # cannot be body, due to 24hr period of Twilio standards
                    content_variables=content_variables # TODO
                    )
                cls.send_msg(
                    message=message, seq_no=seq_no
                )
                successful_aliases.append(to_user.alias)
            except Exception:
                cls.logger.error(traceback.format_exc()) # TODO? 
                continue

        if len(successful_aliases) == 0:
            message = OutgoingMessageData(
                user_id=user_id_to_update,
                job_no=job_no,
                body=ErrorMessage.NO_SUCCESSFUL_MESSAGES
            )
            raise ReplyError(message)

        if user_id_to_update:
            from models.messages.ForwardCallback import ForwardCallback
            session = Session()
            cls.logger.info("Forward Callback Created")
            forward_callback = ForwardCallback(job_no=job_no, seq_no=seq_no, user_id=user_id_to_update, message_context=message_context)
            session.add(forward_callback)
            session.commit()
            if callback:
                callback(forward_callback)
            session.expunge(forward_callback)

    @classmethod
    def construct_forward_metadata(cls, sid, cv_list, users_list):

        if isinstance(sid, list):
            sid_list = sid
        else:
            sid_list = [sid] * len(cv_list)

        forward_metadata = {
            'sid_list': sid_list,
            'cv_list': cv_list,
            'users_list': users_list
        }
        cls.logger.info(forward_metadata)
        return forward_metadata