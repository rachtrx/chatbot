from extensions import db
# from sqlalchemy.orm import 
from typing import List
from constants import messages, PENDING
from dateutil.relativedelta import relativedelta
from utilities import current_sg_time
from config import client

from logs.config import setup_logger

class Message(db.Model):
    logger = setup_logger('models.message_sent')
    __tablename__ = "message"

    sid = db.Column(db.String(80), primary_key=True, nullable=False)
    type = db.Column(db.String(50))
    body = db.Column(db.String(), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.Integer(), nullable=False)
    seq_no = db.Column(db.Integer(), nullable=False)

    job_no = db.Column(db.String, db.ForeignKey('job.job_no'), nullable=True)
    job = db.relationship('Job', backref='messages')

    __mapper_args__ = {
        "polymorphic_on": "type"
    }

    def __init__(self, job_no, sid, body, seq_no):
        print(f"current time: {current_sg_time()}")
        self.job_no = job_no
        self.sid = sid
        self.body = body
        self.timestamp = current_sg_time()
        self.status = PENDING
        if seq_no is not None:
            self.seq_no = seq_no
        else:
            cur_seq_no = self.get_seq_no(job_no)
            self.seq_no = cur_seq_no + 1
        self.logger.info(f"new_message: {self.body}, seq no: {self.seq_no}")
    
    @staticmethod
    def fetch_message(sid):
        message = client.messages(sid).fetch()

        return message.body
    
    @staticmethod
    def create_message(msg_type, *args, **kwargs):
        if msg_type == messages['SENT']:
            from .sent import MessageSent
            new_message =  MessageSent(*args, **kwargs)
        # Add conditions for other subclasses
        elif msg_type == messages['RECEIVED']:
            from .received import MessageReceived
            new_message =  MessageReceived(*args, **kwargs)
        elif msg_type == messages['CONFIRM']:
            from .received import MessageConfirm
            new_message =  MessageConfirm(*args, **kwargs)
        elif msg_type == messages['FORWARD']:
            from .sent import MessageForward
            new_message =  MessageForward(*args, **kwargs)
        else:
            raise ValueError(f"Unknown Message Type: {msg_type}")
        db.session.add(new_message)
        db.session.commit()
        Message.logger.info(f"created new message with seq number {new_message.seq_no}")
        return new_message

    # TO CHECK
    @staticmethod
    def get_seq_no(job_no):
        from models.jobs import Job
        '''finds the sequence number of the message in the job, considering all message types - therefore must use the parent class name instead of "cls"'''

        job = Job.query.filter_by(job_no=job_no).first()

        if len(job.messages) > 0:
            # Then query the messages relationship
            cur_seq_no = max(message.seq_no for message in job.messages)
        else:
            cur_seq_no = 0

        return cur_seq_no

    def commit_status(self, status):
        '''tries to update status'''
        self.status = status
        # db.session.add(self)
        db.session.commit()
        self.logger.info(f"message committed with status {status}")

        return True
    
    @classmethod
    def get_message_by_sid(cls, sid):
        msg = cls.query.filter_by(
            sid=sid
        ).first()
        
        return msg if msg else None
    