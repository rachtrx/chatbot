from extensions import db
# from sqlalchemy.orm import 
import uuid
import logging
from constants import intents, PENDING, OK
import uuid
from utilities import current_sg_time

from logs.config import setup_logger

class Job(db.Model): # system jobs

    logger = setup_logger('models.job')

    __tablename__ = 'job'

    job_no = db.Column(db.String, primary_key=True)
    type = db.Column(db.String(50))
    status = db.Column(db.Integer(), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=current_sg_time())
    
    __mapper_args__ = {
        "polymorphic_identity": "job",
        "polymorphic_on": "type"
    }

    def __init__(self):
        print(f"current time: {current_sg_time()}")
        self.job_no = uuid.uuid4().hex
        self.created_at = current_sg_time()
        self.status = PENDING

    def all_messages_successful(self):
        '''also checks for presence of the other confirm option'''

        all_msgs = self.messages

        all_replied = True

        for msg in all_msgs:
            # self.logger.info("looping msgs in all_messages_successful")
            if msg.type == "message_confirm": # TODO maybe can just use type instead
                other_msg = msg.check_for_other_decision()
                if not other_msg:
                    self.logger.info("2 CONFIRMS NOT FOUND")
                if other_msg and (other_msg.status == OK or msg.status == OK):
                    continue
                elif msg.status != OK:
                    all_replied = False
                    break
            else:
                if msg.status != OK:
                    all_replied = False
                    break

        if all_replied == True and self.status < 400:
            return True
        return False

    # to implement
    def validate_complete(self):
        pass

    def check_for_complete(self):
        if self.status == OK:
            return
        complete = self.validate_complete()
        if complete:
            self.commit_status(OK)
        db.session.commit()

    def commit_status(self, status):
        '''tries to update status'''

        if status is None:
            return
        
        self.status = status
        # db.session.add(self)

        from .user.abstract import JobUser

        if isinstance(self, JobUser) and not self.get_recent_pending_job(self.user.number):
            if (status == OK or status >= 400):
                self.user.is_blocking = False

            else: # PENDING. maybe expecting reply?
                self.user.is_blocking = True

        db.session.commit()

        self.logger.info(f"job status: {status}")

        return True

    def forward_status_not_null(self):
        if self.forwards_status == None:
            return False
        return True
