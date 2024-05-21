from extensions import db, get_session
# from typing import List
from constants import MessageType
from dateutil.relativedelta import relativedelta
from utilities import current_sg_time
from config import twilio
# from sqlalchemy.orm import joinedload

from MessageLoggersetup_logger

import logging

class Message(db.Model):
    logger = setup_logger('models.message_abstract')
    __tablename__ = "message"

    sid = db.Column(db.String(80), primary_key=True, nullable=False)
    type = db.Column(db.String(50))
    body = db.Column(db.String(), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    seq_no = db.Column(db.Integer(), nullable=False)

    job_no = db.Column(db.String, db.ForeignKey('job.job_no'), nullable=True)
    job = db.relationship('Job', backref='messages', lazy='select')

    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": "message"
    }

    def __init__(self, job_no, sid, body, seq_no):
        logging.info(f"current time: {current_sg_time()}")
        self.job_no = job_no
        self.sid = sid
        self.body = body
        self.timestamp = current_sg_time()
        if seq_no is not None:
            self.seq_no = seq_no
        else:
            cur_seq_no = self.get_seq_no(job_no)
            self.seq_no = cur_seq_no + 1
        self.logger.info(f"new_message: {self.body}, seq no: {self.seq_no}")
        
    
    @staticmethod
    def fetch_message(sid):
        message = twilio.messages(sid).fetch()
        return message.body
    
    @staticmethod
    def create_message(msg_type, *args, **kwargs):
        if msg_type == MessageType.SENT:
            from .sent import MessageSent
            new_message =  MessageSent(*args, **kwargs)
        # Add conditions for other subclasses
        elif msg_type == MessageType.RECEIVED:
            from .received import MessageReceived
            new_message =  MessageReceived(*args, **kwargs)
        elif msg_type == MessageType.SELECTION:
            from .received import MessageSelection
            new_message =  MessageSelection(*args, **kwargs)
        elif msg_type == MessageType.FORWARD:
            from .sent import MessageForward
            new_message =  MessageForward(*args, **kwargs)
        else:
            raise ValueError(f"Unknown Message Type: {msg_type}")
        session = get_session()
        session.add(new_message)
        session.commit()
        Message.logger.info(f"created new message with seq number {new_message.seq_no}")
        return new_message
    
    # TO CHECK
    @staticmethod
    def get_seq_no(job_no):
        '''finds the sequence number of the message in the job, considering all message types - therefore must use the parent class name instead of "cls"'''

        session = get_session()
        for instance in session.identity_map.values():
            logging.info(f"Instance in get_seq_no session: {instance}")

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