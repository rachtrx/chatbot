import os
from sqlalchemy.ext.declarative import declared_attr

from extensions import db, Session, twilio

from MessageLogger import setup_logger

from models.jobs.base.constants import MessageType, Status

from models.messages.ForwardCallback import ForwardCallback

# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class SentMessageStatus(db.Model):

    __tablename__ = "sent_message_status"

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')
    logger.propagate = False

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    status = db.Column(db.String(10), nullable=False)

    message = db.relationship('Message', backref='sent_status', lazy='select')

    def __init__(self, sid):
        self.sid = sid
        self.status = Status.PENDING
    
    # FOLLOWING FUNCTIONS ARE CALLED FROM THE HTTTP CALLBACK

    def update_message_body(self):
        message = twilio.messages(self.sid).fetch()
        self.message.body = message.body
    
    def update_message_status(self, status):
        
        if status == "sent":
            pass # USE TWILIO LOGS FOR DETAILS

        elif status == "delivered" or status == "failed":

            session = Session()

            self.status = Status.COMPLETED if status == "delivered" else Status.FAILED

            session.commit()

            self.logger.info(f"message {self.sid} committed with COMPLETED")
            
            if self.message.msg_type == MessageType.FORWARD:
                self.logger.info(f"forwarded message {self.sid} was forwarded successfully")
                
                callback = session.query(ForwardCallback).get((self.message.job_no, self.message.seq_no))
                if callback and callback.update_count > 0:
                    self.logger.info(f"update count: {callback.update_count}")
                    callback.update_on_forwards(use_name_alias=True)

        return None
    
    
    

