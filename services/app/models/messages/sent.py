from extensions import db
from constants import messages, PENDING_CALLBACK, FAILED, OK, PENDING
import os
import json
from config import client
from .abstract import Message
import time
import logging
import threading

from utilities import loop_relations, join_with_commas_and, print_all_dates

from models.users import User
from models.jobs.unknown.job_unknown import JobUnknown
from models.jobs.user.abstract import JobUser
from models.jobs.system.abstract import JobSystem

from logs.config import setup_logger


# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class MessageSent(Message):

    logger = setup_logger('models.message_sent')
    __tablename__ = "message_sent"

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    is_expecting_reply = db.Column(db.Boolean, nullable=False)
    
    # job = db.relationship('Job', backref='sent_messages')

    __mapper_args__ = {
        "polymorphic_identity": "message_sent",
    }

    def __init__(self, job_no, sid, is_expecting_reply, seq_no=None, body=None):
        super().__init__(job_no, sid, body, seq_no) # initialise message
        self.is_expecting_reply = is_expecting_reply

    def commit_message_body(self, body):
        self.body = body
        self.logger.info(f"message body committed: {self.body}")
        db.session.commit()

    @classmethod
    def send_msg(cls, msg_type, reply, job, **kwargs):

        '''kwargs supplies the init variables to Message.create_messages() which call the following init functions based on the msg_type: 
        
        msg_type == messages['SENT']:
        MessageSent.__init__(self, job_no, sid, is_expecting_reply, seq_no=None, body=None): 

        msg_type == messages['FORWARD']:
        MessageForward.__init__(self, job_no, sid, is_expecting_reply, seq_no, to_name):

        job_no, sid, and is_expecting_reply are updated; the rest has to be passed as kwargs.

        For MessageSent, additional kwargs is not required (min total 3 args)
        For MessageForward, additional kwargs is required for seq_no and relation (min total 5 args)
        '''

        if msg_type == messages['FORWARD']:
            to_no = kwargs['relation'].sg_number # forward message
            kwargs["is_expecting_reply"] = getattr(job, 'is_expecting_relations_reply', False)
        else: # SENT
            if isinstance(job, JobUnknown):
                to_no = job.from_no # unknown number
            elif isinstance(job, JobUser):
                to_no = job.user.sg_number # user number
            elif isinstance(job, JobSystem):
                to_no = job.root_user.sg_number # user number
            kwargs["is_expecting_reply"] = getattr(job, 'is_expecting_user_reply', False)

        if isinstance(reply, tuple):
            sid, cv = reply
            sent_message_meta = cls._send_template_msg(sid, cv, to_no)
        else:
            sent_message_meta = cls._send_normal_msg(reply, to_no)

        kwargs["job_no"] = job.job_no
        kwargs["sid"] = sent_message_meta.sid

        sent_msg = Message.create_message(msg_type, **kwargs)

        sent_msg.commit_status(PENDING_CALLBACK)
        return sent_msg

    @staticmethod
    def _send_template_msg(content_sid, content_variables, to_no):

        print(content_variables)

        sent_message_meta = client.messages.create(
                to=to_no,
                from_=os.environ.get("MESSAGING_SERVICE_SID"),
                content_sid=content_sid,
                content_variables=content_variables if content_variables is not None else {}
            )

        return sent_message_meta

    @staticmethod
    def _send_normal_msg(body, to_no):
        '''so far unused'''
        sent_message_meta = client.messages.create(
            from_=os.environ.get("TWILIO_NO"),
            to=to_no,
            body=body
        )
        return sent_message_meta
    
    @staticmethod
    def _send_error_msg(body="Something went wrong with the sync"):
        sent_message_meta = client.messages.create(
            from_=os.environ.get("TWILIO_NO"),
            to=os.environ.get("TEMP_NO"),
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
        return User.query.filter_by(name=self.to_name).first()

    __mapper_args__ = {
        "polymorphic_identity": "message_forward",
        'inherit_condition': sid == MessageSent.sid
    }

    def __init__(self, job_no, sid, is_expecting_reply, seq_no, relation):
        self.logger.info(f"forward message created for {relation.name}")
        super().__init__(job_no, sid, is_expecting_reply, seq_no) # initialise message, body is always none since need templates to forward
        self.to_name = relation.name
    
    @staticmethod
    def acknowledge_decision():
        return f"All messages have been sent successfully."
    
    @classmethod
    def check_message_forwarded(cls, job, seq_no):
        time.sleep(5) 

        from app import app

        with app.app_context():

            try:
                job = db.session.merge(job)
            except:
                job = db.session.add(job)
            
            db.session.refresh(job)

            forwarded_msgs = cls.query.filter(
                cls.job_no == job.job_no,
                cls.seq_no == seq_no,
            )

            logging.info("in threading function")
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

            cls.send_msg(messages['SENT'], reply, job)

            db.session.refresh(job)

            if not len(failed) > 0 and not len(unknown) > 0: 
                job.forwards_status = OK
            elif len(unknown) > 0:
                job.forwards_status = PENDING
            else:
                job.forwards_status = FAILED

            db.session.commit()
            job.check_for_complete()


    ########################
    # CHATBOT FUNCTIONALITY
    ########################
    
    @classmethod
    def forward_template_msges(cls, content_variables_and_users_list, job):

        new_seq_no = MessageSent.get_seq_no(job.job_no) + 1

        for content_variables, relation in content_variables_and_users_list:
            cls.send_msg(
                msg_type=messages['FORWARD'],
                reply=(job.content_sid, content_variables), 
                job=job, 
                seq_no=new_seq_no,
                relation=relation
            )

        callback_thread = threading.Thread(target=cls.check_message_forwarded, args=(job, new_seq_no)) # need to pass number as object not available in thread due to lazy loading of user
        callback_thread.start()


    ###################################################
    # FOR SENDING MESSAGES TO ALL RELATIONS OF ONE PERSON
    ###################################################

    @staticmethod
    def get_cv_and_users_list(get_cv_func, *func_args):
        '''This function sets up the details of the forward to HOD and reporting officer message
        
        With the decorator, it returns a list as [(content_variables, relation_name), (content_variables, relation_name)]'''

        cv_and_users_list = get_cv_func(*func_args) # for the cv funcs with loop relations, user is passed as the first argument in func args

        for i, (cv, user) in enumerate(cv_and_users_list):
            cv_and_users_list[i] = (json.dumps(cv), user)

        return cv_and_users_list


    #################################
    # CV TEMPLATES FOR MANY MESSAGES
    #################################
    
    @staticmethod
    @loop_relations
    def get_forward_mc_cv(relation, job):

        return [{
            '1': relation.name,
            '2': job.user.name,
            '3': str(job.duration),
            '4': print_all_dates([date for month_date_arr in job.new_monthly_dates.values() for date in month_date_arr])
        }, relation]
    