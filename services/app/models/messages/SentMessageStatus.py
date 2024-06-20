import os
from sqlalchemy.types import Enum as SQLEnum

from extensions import db, get_session, twilio

from models.jobs.base.constants import MessageType, Status

from models.messages.ForwardCallback import ForwardCallback

# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class SentMessageStatus(db.Model):

    __tablename__ = "sent_message_status"

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    status = db.Column(SQLEnum(Status), nullable=False)

    message = db.relationship('MessageBase', backref='sent_status', lazy='select')

    def __init__(self, sid):
        self.sid = sid
        self.status = Status.PENDING_CALLBACK

    def commit_status(self, status):
        self.logger.info(f"trying to commit status {status}")
        session = get_session()
        '''tries to update status'''
        self.status = status
        session.commit()

        message = session.query(SentMessageStatus).filter_by(sid=self.sid).first()
        self.logger.info(f"message status: {message.status}, passed status: {status}")
        return True
    
    # FOLLOWING FUNCTIONS ARE CALLED FROM THE HTTTP CALLBACK

    def update_message_body(self):
        message = twilio.messages(self.sid).fetch()
        self.message.body = message.body
    
    def update_message_status(self, status):
        
        if status == "sent":
            pass # USE TWILIO LOGS FOR DETAILS

        elif status == "delivered":

            self.status = Status.COMPLETED
            logging.info(f"message {self.sid} committed with COMPLETED")
            
            if self.message.msg_type == MessageType.FORWARD:
                logging.info(f"forwarded message {self.sid} was sent successfully")
                session = get_session()

                callback = session.query(ForwardCallback).get((self.message.job_no, self.message.seq_no))
                if callback and callback.update_count > 0:
                    callback.update_on_forwards(use_name_alias=True)

            # reply message expecting user reply. just to be safe, specify the 2 types of messages
        
        elif status == "failed":
            # job immediately fails
            message.commit_status(Status.SERVER_ERROR)

            if message.type == "message_forward" and self.forwards_status_sent():
                self.update_user_on_forwards(message.seq_no, self.map_job_type())
            else:
                self.commit_status(JobStatus.SERVER_ERROR) # forward message failed is still ok to some extent, especially if the user cancels afterwards. It's better to inform about the cancel


            if self.type == "job_es": # TODO should probably send to myself
                Message.execute(MessageType.SENT, (os.environ.get("ERROR_SID"), None), self)

        return None
    
    
    

