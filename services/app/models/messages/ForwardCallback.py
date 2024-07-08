import os
import traceback

from sqlalchemy.ext.declarative import declared_attr

from extensions import db, Session
from MessageLogger import setup_logger

from models.jobs.base.constants import OutgoingMessageData, MessageType, ForwardStatus, Status
from models.jobs.base.utilities import join_with_commas_and, run_new_context

from models.messages.MessageKnown import MessageKnown

class ForwardCallback(db.Model):
    __tablename__ = 'forward_callback'

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')
    logger.propagate = False

    job_no = db.Column(db.String(32), db.ForeignKey('job.job_no'), primary_key=True, nullable=False)
    seq_no = db.Column(db.Integer, primary_key=True, nullable=False)

    job = db.relationship('Job', backref='forward_callbacks', lazy='select')

    user_id = db.Column(db.ForeignKey("users.id"), nullable=False)
    user = db.relationship('User', backref='callbacks', lazy='select')

    update_count = db.Column(db.Integer, nullable=False)
    message_context = db.Column(db.String(64), nullable=False)

    def __init__(self, job_no, seq_no, user_id, message_context):
        self.job_no = job_no
        self.seq_no = seq_no
        self.user_id = user_id
        self.update_count = 0
        self.message_context = message_context

    @run_new_context
    def update_on_forwards(self, use_name_alias): # add job_no, seq_no??
        statuses = self.check_message_forwarded()

        content_variables = {
            '1': self.message_context, # "The following personnel have been notified about <message_type>"
            '2': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.COMPLETED]) if len(statuses.COMPLETED) > 0 else "None",
            '3': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.FAILED]) if len(statuses.FAILED) > 0 else "None",
            '4': join_with_commas_and([user.alias if use_name_alias else user.name for user in statuses.PENDING]) if len(statuses.PENDING) > 0 else "None"
        }

        message = OutgoingMessageData(
            msg_type=MessageType.SENT,
            user_id=self.user_id, 
            job_no=self.job_no, 
            content_sid=os.getenv("FORWARD_MESSAGES_CALLBACK_SID"),
            content_variables=content_variables
        )

        MessageKnown.send_msg(message)

        self.update_count += 1

        self.logger.info(f"Update count: {self.update_count}")

    def check_message_forwarded(self):

        session = Session()
        self.logger.info(f"session id in check_message_forwarded: {id(session)}")

        for instance in session.identity_map.values():
            self.logger.info(f"Instance in check_message_forwarded session: {instance}")

        try:
            self.logger.info("in threading function")

            forwarded_msgs = session.query(
                MessageKnown
            ).filter(
                MessageKnown.job_no == self.job_no,
                MessageKnown.seq_no == self.seq_no,
                MessageKnown.msg_type == MessageType.FORWARD,
            ).all()

            if not forwarded_msgs:
                return

            sids = [f_msg.sid for f_msg in forwarded_msgs]

            # Fetch all SentMessageStatus records in one go using `in_`
            from models.messages.SentMessageStatus import SentMessageStatus
            sent_messages = session.query(SentMessageStatus).filter(SentMessageStatus.sid.in_(sids)).all()
            sent_messages_dict = {sent_msg.sid: sent_msg.status for sent_msg in sent_messages}

            self.logger.info([sid, status] for sid, status in sent_messages_dict.items())

            statuses = ForwardStatus()
            for f_msg in forwarded_msgs:
                status = sent_messages_dict.get(f_msg.sid)
                if status == Status.COMPLETED:
                    statuses.COMPLETED.append(f_msg.user)
                elif status == Status.FAILED:
                    statuses.FAILED.append(f_msg.user)
                else: # Assuming remaining are PENDING_CALLBACK
                    statuses.PENDING.append(f_msg.user)
            return statuses
            
        except Exception as e:
            self.logger.error(traceback.format_exc())
            raise