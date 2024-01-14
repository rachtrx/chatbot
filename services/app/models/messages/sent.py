from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc, union_all
from typing import List
import uuid
from constants import messages, TEMP, PENDING_CALLBACK, FAILED, OK
import re
from dateutil.relativedelta import relativedelta
import os
from utilities import current_sg_time, get_relations_name_and_no_list, print_relations_list
import json
from config import client
from models.exceptions import ReplyError
from .abstract import Message
import time
import logging
import threading

from utilities import loop_relations, join_with_commas_and, print_all_dates

from logs.config import setup_logger


# SECTION PROBLEM: If i ondelete=CASCADE, if a hod no longer references a user the user gets deleted
# delete-orphan means that if a user's HOD or RO is no longer associated, it gets deleted

class MessageSent(Message):

    logger = setup_logger('models.message_sent')
    __tablename__ = "message_sent"

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    is_expecting_user_reply = db.Column(db.Boolean, nullable=False)
    
    # job = db.relationship('Job', backref='sent_messages')

    __mapper_args__ = {
        "polymorphic_identity": "message_sent",
    }

    def __init__(self, job_no, sid, body=None, seq_no=None, is_expecting_user_reply=False):
        super().__init__(job_no, sid, body, seq_no) # initialise message
        self.is_expecting_user_reply = is_expecting_user_reply

    def commit_message_body(self, body):
        self.body = body
        self.logger.info(f"message body committed: {self.body}")
        db.session.commit()

    @classmethod
    def send_msg(cls, reply, job, to_no=None, msg_type=messages['SENT']):

        if to_no == None:
            to_no = job.user.sg_number

        if isinstance(reply, tuple):
            sid, cv = reply
            sent_message_meta = cls._send_template_msg(sid, cv, to_no)
        else:
            sent_message_meta = cls._send_normal_msg(reply, to_no)

        kwargs = {
            "msg_type": msg_type, # either sent or forward
            "job_no": job.job_no,
            "sid": sent_message_meta.sid,
            "is_expecting_user_reply": job.is_expecting_user_reply
        }

        if msg_type == messages['FORWARD']:
            kwargs['to_no'] = to_no

        sent_msg = Message.create_message(**kwargs)

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
    to_no = db.Column(db.Integer(), db.ForeignKey('users.number'), nullable=False)
    # forward_status = db.Column(db.Integer(), nullable=False)
    # message_pending_forward = db.Column(db.ForeignKey("message.sid"))

    to_user = db.relationship('User', backref='forwarded_messages')

    __mapper_args__ = {
        "polymorphic_identity": "message_forward",
        'inherit_condition': sid == MessageSent.sid
    }

    def __init__(self, job_no, sid, to_no, seq_no, body=None, is_expecting_user_reply=None):
        self.logger.info(f"forward message created for {to_no}")
        super().__init__(job_no, sid, body, seq_no, is_expecting_user_reply) # initialise message
        self.to_no = to_no
    
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
                to_name = f_msg.to_user.name

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

            cls.send_msg(reply, job)

            db.session.refresh(job)

            if not len(failed) > 0 and not len(unknown) > 0: 
                job.forwards_complete = True
                db.session.commit()

            job.check_for_complete()


    ########################
    # CHATBOT FUNCTIONALITY
    ########################
    
    @classmethod
    def forward_template_msges(cls, content_variables_and_users_list, content_sid, job):

        new_seq_no = MessageSent.get_seq_no(job.job_no) + 1

        for content_variables, relation in content_variables_and_users_list:
            forward_message_meta = cls.send_msg((content_sid, content_variables), job, relation.sg_number, messages['FORWARD'])

            cls.logger.info(f"forward message for {forward_message_meta.sid} has been created")

        callback_thread = threading.Thread(target=cls.check_message_forwarded, args=(job, new_seq_no)) # need to pass number as object not available in thread due to lazy loading of user
        callback_thread.start()



    ###################################################
    # FOR SENDING MESSAGES TO ALL RELATIONS OF ONE PERSON
    ###################################################

    @staticmethod
    @loop_relations
    def get_cv_and_relations_list(relation, get_cv_func, *func_args):
        '''This function sets up the details of the forward to HOD and reporting officer message
        
        With the decorator, it returns a list as [(content_variables, relation_name), (content_variables, relation_name)]'''

        content_variables = get_cv_func(relation, *func_args)

        content_variables_json = json.dumps(content_variables)
        
        MessageForward.logger.info(json.dumps(content_variables, indent=4))
        
        return (content_variables_json, relation)


    #################################
    # CV TEMPLATES FOR MANY MESSAGES
    #################################
    
    @staticmethod
    def get_forward_mc_cv(relation, job):

        return {
            '1': relation.name,
            '2': job.user.name,
            '3': str(job.duration),
            '4': print_all_dates([date for month_date_arr in job.new_monthly_dates.values() for date in month_date_arr])
        }
    