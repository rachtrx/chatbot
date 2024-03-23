from datetime import datetime, timedelta, date
from extensions import db, get_session
from constants import errors, OK, CHANGED, DECISIONS, intents, MC_DECISIONS
from dateutil.relativedelta import relativedelta
import os
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, join_with_commas_and, get_latest_date_past_8am, log_instances
from overrides import overrides

from logs.config import setup_logger

from models.users import User
from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUser
from models.leave_records import LeaveRecord

from constants import leave_keywords, leave_types
import re
import traceback
from .utils_leave import dates

class JobLeave(JobUser):
    __tablename__ = "job_leave"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    forwards_status = db.Column(db.Integer, default=None, nullable=True)
    local_db_updated = db.Column(db.Boolean(), nullable=False)
    leave_type = db.Column(db.String(20), nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_leave"
    }

    logger = setup_logger('models.job_leave')
    cancel_msg = errors['WRONG_DATE']
    cancel_after_fail_msg = errors['JOB_FAILED_MSG']
    timeout_msg = errors['TIMEOUT_MSG']
    confirm_after_cancel_msg = errors['CONFIRMING_CANCELLED_MSG']
    not_replying_to_last_msg = errors['NOT_LAST_MSG']

    def __init__(self, name):
        super().__init__(name)
        self.local_db_updated = False

    def set_leave_type(self):
        leave_keyword_patterns = re.compile(leave_keywords, re.IGNORECASE)
        leave_match = leave_keyword_patterns.search(self.user_str)

        if leave_match:
            matched_term = leave_match.group(0) if leave_match else None
            for leave_type, phrases in leave_types.items():
                if matched_term.lower() in [phrase.lower() for phrase in phrases]:
                    return leave_type
            # UNKNOWN ERROR... keyword found but couldnt lookup
        
        content_sid = os.environ.get('SELECT_LEAVE_TYPE_SID')
        cv = None
        self.is_expecting_user_reply = True
        raise ReplyError(err_message=(content_sid, cv), job_status=None)
    
    @overrides
    def bypass_validation(self, decision):
        if self.local_db_updated and decision == DECISIONS['CANCEL']:
            return True
        return False

    @overrides
    def is_cancel_job(self, decision):
        if decision == DECISIONS['CANCEL']:
            return True
        return False
    
    def update_info(self, job_information):
        if "dates" in job_information:
            job_information['dates'] = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in job_information['dates']]
            self.dates_to_update = job_information['dates']
            self.duration = len(self.dates_to_update)
            self.leave_type = job_information['leave_type']
        elif "initial_msg" in job_information:
            self.user_str = job_information['initial_msg']
        else:
            raise ReplyError("Either the initial message or the dates were lost")

    
    def handle_request(self):
        from models.messages.received import MessageConfirm
        self.logger.info("job set with expects")

        # self.background_tasks = []

        # if it has the user string, its the first msg, or a retry message. user_str attribute it set either in update_info or during job initialisation
        if getattr(self, "user_str", None):


            if getattr(self.received_msg, 'decision', None):
                self.logger.info(f"Checking for decision in handle request with user string: {self.received_msg.decision}")

            # if not retry message
            if not getattr(self.received_msg, 'decision', None):
                logging.info("using regex to set leave type")
                self.leave_type = self.set_leave_type()
            else:
                # retry message
                self.leave_type = MC_DECISIONS.get(self.received_msg.decision, None) # previously had bus sometimes when not using str()
            
            if not self.leave_type:
                raise ReplyError(errors['UNKNOWN_ERROR'])

            self.received_msg.reply = self.handle_user_entry_action()

        elif isinstance(self.received_msg, MessageConfirm) and getattr(self.received_msg, "decision", None):
            # these 2 functions are implemented with method overriding
            decision = self.received_msg.decision
            if decision != DECISIONS['CONFIRM']:
                logging.error(f"UNCAUGHT DECISION {decision}")
                raise ReplyError(errors['UNKNOWN_ERROR'])
            self.validate_confirm_message() # checks for ReplyErrors based on state
            self.received_msg.reply = self.handle_user_reply_action()
                
        else:
           raise ReplyError(errors['UNKNOWN_ERROR'])

    @overrides
    def validate_confirm_message(self):
        pass

    @overrides
    def handle_user_reply_action(self):
        updated_db_msg = LeaveRecord.insert_local_db(self)
        self.content_sid = os.environ.get("LEAVE_NOTIFY_SID")
        self.set_cv_func = self.get_forward_leave_cv # must set here because Cancel will also call super().. if set in forward_messages(), then McCancel will use the same cv
        self.forward_messages()
        reply = f"{updated_db_msg}, messages have been forwarded. Pending success..."
        return reply

    @overrides
    def handle_user_entry_action(self):

        start_date_status, overlap_status = self.generate_base()

        self.logger.info(f"STATUSES: {start_date_status}, {overlap_status}")

        if overlap_status == CHANGED and start_date_status == CHANGED:
            self.set_cv_func = self.get_later_start_date_and_overlap_confirm_leave_cv
            content_sid = os.environ.get("LEAVE_LATER_START_DATE_AND_OVERLAP_CONFIRMATION_CHECK_SID")
        elif overlap_status == CHANGED: # check that it is an leave message
            self.set_cv_func = self.get_overlap_confirm_leave_cv
            content_sid = os.environ.get("LEAVE_OVERLAP_CONFIRMATION_CHECK_SID")
        elif start_date_status == CHANGED:
            self.set_cv_func = self.get_later_start_date_confirm_leave_cv
            content_sid = os.environ.get("LEAVE_LATER_START_DATE_CONFIRMATION_CHECK_SID")
        elif start_date_status == OK and overlap_status == OK: # status is OK
            self.set_cv_func = self.get_confirm_leave_cv
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_SID")
        else:
            self.logger.error(f"UNCAUGHT STATUS {start_date_status}, {overlap_status}")
            raise ReplyError(errors['UNKNOWN_ERROR'])

        self.printed_name_and_no_list = self.print_relations_list() # no need names list
        
        cv = self.set_cv()

        self.is_expecting_user_reply = True

        return (content_sid, cv)
    
    @overrides
    def forward_messages(self):
        super().forward_messages()

        if len(self.successful_forwards) > 0:
            return f"messages have been successfully forwarded to {join_with_commas_and(self.successful_forwards)}. Pending delivery success..."
        else:
            return f"All messages failed to send. You might have to update them manually, sorry about that"
    
    @overrides
    def validate_complete(self):
        self.logger.info(f"user: {self.user.name}, messages: {self.messages}")
        
        if self.local_db_updated and self.forwards_status == OK:
            last_message_replied = self.all_messages_successful() # IMPT check for any double decisions before unblocking
            if last_message_replied:
                self.logger.info("all messages successful")
                return True
        self.logger.info("all messages not successful")
        return False
    
    def get_cache_data(self):
        if getattr(self, 'is_expecting_user_reply', False) and getattr(self, 'dates_to_update') and getattr(self, 'leave_type'):
            return {
                "status": self.status,
                "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
                "sent_sid": self.sent_msg.sid,
                "leave_type": self.leave_type,
                "job_no": self.job_no
            }
        else:
            return None
    
    # def run_background_tasks(self):
    #     '''implement handle_replied_future_results and check_for_complete in child class'''
    #     session = get_session()
    #     future_results = super().run_background_tasks()
    #     if future_results and len(future_results) > 0:
         
    #         logging.info(f"background tasks done")
    #         log_instances(session, "run_replied_background_tasks")
    #         self.handle_future_results(future_results)
    #         logging.info(f"messages forwarded: {self.forwards_status}")
    #         self.check_for_complete()

    #     if getattr(self, 'is_expecting_user_reply', False) and getattr(self, 'dates_to_update') and getattr(self, 'leave_type'):
    #         return {
    #             "status": self.status,
    #             "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
    #             "sent_sid": self.sent_msg.sid,
    #             "leave_type": self.leave_type,
    #             "job_no": self.job_no
    #         }
    #     else:
    #         return None
        

    # def handle_future_results(self, future_results):
    #     self.logger.info("IN HANDLE FUTURE RESULTS")
    #     forwards_status = future_results[0]
    #     self.commit_status(forwards_status, _forwards=True)

    ########
    # ENTRY
    ########

    def generate_base(self):
        '''Generates the basic details of the MC, including the start, end and duration of MC'''

        self.start_date = self.end_date = self.duration = None

        self.logger.info(f"User string in generate base: {self.user_str}")

        try:

            # self.duration is extracted duration
            if dates.duration_extraction(self.user_str):
                self.duration = int(dates.duration_extraction(self.user_str))

            duration_c = self.set_start_end_date() # checks for conflicts and sets the dates

            self.logger.info("start generate_base")
            
            if duration_c:
                # if there are specified dates and no duration
                self.logger.info(f"{self.end_date}, {self.duration}, {duration_c}, {self.start_date}")
                if self.duration == None:
                    self.duration = duration_c
                # if there are specified dates and duration is wrong
                elif self.duration and self.duration != duration_c:

                    body = f'The duration from {self.start_date} to {self.end_date} ({duration_c}) days) do not match with {self.duration} days. Please send another message in the form "MC from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

                    raise DurationError(body)
                
            # if there is only 1 specified date and duration_e
            elif self.duration and self.start_date:
                self.end_date = self.start_date + timedelta(days=max(int(self.duration) - 1, 0))

            #note: if end date and duration, start date is assumed to be today and duration error would have been flagged out
            elif self.start_date:
                self.end_date = self.start_date
                self.duration = 1

            # only duration e and no dates
            else: 
                try: # duration specified
                    self.start_date, self.end_date = dates.calc_start_end_date(self.duration) # sets self.start_date, self.end_date
                except Exception: # start, end dates and duration not specified
                    raise DurationError(errors['DATES_NOT_FOUND'])
            
            self.logger.info(f"{self.end_date}, {self.duration}, {duration_c}, {self.start_date}")
        
            start_date_status = self.validate_start_date()
        
            overlap_status = self.validate_overlap()

            self.logger.info(f"Dates validated")
            
            return start_date_status, overlap_status
                
        except DurationError as e:
            logging.error(f"error message is {e.message}")
            raise ReplyError(e.message)
        
    def duration_calc(self):
        '''ran when start_date and end_date is True, returns duration between self.start_time and self.end_time. 
        if duration is negative, it adds 1 to the year. also need to +1 to duration since today is included as well'''

        # if current month > start month
        if self.start_date.month < current_sg_time().month:
            self.start_date += relativedelta(years=1)

        duration = (self.end_date - self.start_date).days + 1
        while duration < 0:
            self.end_date += relativedelta(years=1)
            duration = (self.end_date - self.start_date).days + 1

        logging.info(f'duration: {duration}')

        return duration

        
    def set_start_end_date(self):
        '''This function uses self.user_str and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = dates.named_month_extraction(self.user_str)
        ddmm_start, ddmm_end = dates.named_ddmm_extraction(self.user_str)
        day_start, day_end = dates.named_day_extraction(self.user_str)
        
        start_dates = [date for date in [named_month_start, ddmm_start, day_start] if date is not None]
        end_dates = [date for date in [named_month_end, ddmm_end, day_end] if date is not None]

        self.logger.info(f"{start_dates}, {end_dates}")

        if len(start_dates) > 1:

            body = f'Conflicting start dates {", ".join(str(date) for date in start_dates)}. Please send another message in the form "MC from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise DurationError(body)
        if len(end_dates) > 1:
            
            body = f'Conflicting end dates {", ".join(str(date) for date in end_dates)}. Please send another message in the form "MC from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise DurationError(body)
        
        if len(start_dates) == 1:
            self.start_date = start_dates[0]
        if len(end_dates) == 1:
            self.end_date = end_dates[0]
        
        if self.start_date and self.end_date:
            self.logger.info(f"{type(self.start_date)} {type(self.end_date)}")
            # try:
            # TODO SET NEW DATES IF ITS 2024

            return self.duration_calc() # returns duration_c
            # except:
            #     return False
        
        return None
        
    def validate_start_date(self):
        session = get_session()
        '''Checks if start date is valid, otherwise tries to set the start date and duration'''
        earliest_possible_date = current_sg_time().date()
        earliest_possible_date = get_latest_date_past_8am()
        
        self.logger.info(earliest_possible_date)
        self.logger.info(f"{self.start_date}, {self.end_date}")
        if self.start_date < earliest_possible_date:
            if self.end_date < earliest_possible_date:
                self.logger.info("date is too early cannot be fixed")
                body = f"Hi {self.user.name}, I am no longer able to add your MC if it is past 8am today, and no other days could be extracted. Please only send dates after today if it is past 8am, thank you!"
                raise DurationError(body)
            else:
                self.logger.info("date is too early but can be fixed")
                self.start_date = earliest_possible_date
                self.duration = (self.end_date - self.start_date).days + 1
                session.commit()
                logging.info(f"committed in validate_start_date in session {id(session)}")
                status = CHANGED
        else:
            status = OK
        
        return status

        
    def validate_overlap(self):
        '''
        checks if the dates overlap, sets self.duplicate_dates, self.dates_to_update, and self.duration
        '''
        # IMPT This is the very last validation. If the user confirms, it bypasses another validation check!
        self.check_for_duplicates() # sets the duplicate dates

        if len(self.duplicate_dates) != 0 and len(self.dates_to_update) != 0:
            self.logger.info("duplicates but can be fixed")
            status = CHANGED
        elif len(self.duplicate_dates) != 0:
            self.logger.info("duplicates cannot be fixed")
            raise DurationError(errors["ALL_DUPLICATE_DATES"])
        else:
            status = OK
        
        return status

    def check_for_duplicates(self):

        session = get_session()

        logging.info(f"in check_for_duplicates: {self.start_date}, {self.end_date}")
        start_date, duration = self.start_date, self.duration # these are actually functions

        def daterange():
            for n in range(duration):
                yield start_date + timedelta(n)

        all_dates_set = set(daterange())
        duplicate_records = LeaveRecord.get_duplicates(self)
        duplicate_dates_set = set([record.date for record in duplicate_records])
        logging.info(f"Duplicate dates set: {duplicate_dates_set}")

        non_duplicate_dates_set = all_dates_set - duplicate_dates_set

        self.duplicate_dates = sorted(list(duplicate_dates_set))
        self.dates_to_update = sorted(list(non_duplicate_dates_set))
        # logging.info(f"Type of date: {type(self.dates_to_update[0])}")

        self.duration = len(self.dates_to_update)

        logging.info(f"committed in check_for_duplicates in session {id(session)}")

        session.commit()
    
    def create_cancel_job(self, user_str):
        return self.create_job(intents['CANCEL_LEAVE'], user_str, self.user.name, self.job_no, self.leave_type)

    #################################
    # CV TEMPLATES FOR MANY MESSAGES
    #################################
    
    @JobUser.loop_relations # just need to pass in the user when calling get_forward_leave_cv
    def get_forward_leave_cv(self, relation):
        '''LEAVE_NOTIFY_SID; The decorator is for SENDING MESSAGES TO ALL RELATIONS OF ONE PERSON'''

        return {
            '1': relation.alias,
            '2': self.user.alias,
            '3': self.leave_type.lower(),
            '4': f"{str(self.duration)} {'day' if self.duration == 1 else 'days'}",
            '5': print_all_dates(self.dates_to_update, date_obj=True)
        }
        
    def get_confirm_leave_cv(self):

        return {
            '1': self.user.alias,
            '2': self.leave_type.lower(),
            '3': datetime.strftime(self.start_date, '%d/%m/%Y'),
            '4': datetime.strftime(self.end_date, '%d/%m/%Y'),
            '5': str(self.duration),
            '6': self.printed_name_and_no_list,
            '7': DECISIONS['CONFIRM'],
            '8': DECISIONS['CANCEL']
        }

    def get_later_start_date_confirm_leave_cv(self):

        return {
            '1': self.user.alias,
            '2': self.leave_type.lower(),
            '3': datetime.strftime(self.start_date, '%d/%m/%Y'),
            '4': datetime.strftime(self.end_date, '%d/%m/%Y'),
            '5': str(self.duration),
            '6': self.printed_name_and_no_list,
            '7': DECISIONS['CONFIRM'],
            '8': DECISIONS['CANCEL']
        }

    def get_overlap_confirm_leave_cv(self):

        return {
            '1': self.user.alias,
            '2': print_all_dates(self.duplicate_dates, date_obj=True),
            '3': self.leave_type.lower(),
            '4': print_all_dates(self.dates_to_update, date_obj=True),
            '5': str(self.duration),
            '6': self.printed_name_and_no_list,
            '7': DECISIONS['CONFIRM'],
            '8': DECISIONS['CANCEL']
        }

    def get_later_start_date_and_overlap_confirm_leave_cv(self):
        
        return {
            '1': self.user.alias,
            '2': print_all_dates(self.duplicate_dates, date_obj=True),
            '3': self.leave_type.lower(),
            '4': print_all_dates(self.dates_to_update, date_obj=True),
            '5': str(self.duration),
            '6': self.printed_name_and_no_list,
            '7': DECISIONS['CONFIRM'],
            '8': DECISIONS['CANCEL']
        }


class JobLeaveCancel(JobLeave):
    __tablename__ = "job_leave_cancel"
    job_no = db.Column(db.ForeignKey("job_leave.job_no"), primary_key=True) # TODO on delete cascade?
    initial_job_no = db.Column(db.ForeignKey("job_leave.job_no"), unique=True, nullable=False)

    original_job = db.relationship('JobLeave', foreign_keys=[initial_job_no], backref=db.backref('cancelled_job', uselist=False, remote_side=[JobLeave.job_no]), lazy='select')

    __mapper_args__ = {
        "polymorphic_identity": "job_leave_cancel",
        'inherit_condition': (job_no == JobLeave.job_no),
    }

    def __init__(self, name, initial_job_no, leave_type):
        super().__init__(name)
        self.initial_job_no = initial_job_no
        self.local_db_updated = False
        self.leave_type = leave_type

    def validate_confirm_message(self):        
        self.logger.info(f"original job status: {self.original_job.status}")
        
        if self.original_job.local_db_updated != True:
            raise ReplyError(errors['job_leave_FAILED'])
        
    def handle_request(self):
        from models.messages.received import MessageConfirm
        self.logger.info("job set with expects")

        # if it has the user string, its the first msg, or a retry message. user_str attribute it set either in update_info or during job initialisation
        
        decision = self.received_msg.decision
        if decision != DECISIONS['CANCEL']:
            logging.error(f"UNCAUGHT DECISION {decision}")
            raise ReplyError(errors['UNKNOWN_ERROR'])
        self.validate_confirm_message() # checks for ReplyErrors based on state
        self.received_msg.reply = self.handle_user_reply_action()
        
    @overrides
    def forward_messages(self):
        super().forward_messages()

        if len(self.successful_forwards) > 0:
            return f"messages have been successfully forwarded to {join_with_commas_and(self.successful_forwards)}. Pending delivery success..."
        else:
            return f"All messages failed to send. You might have to update them manually, sorry about that"

    @overrides
    def handle_user_reply_action(self):
        updated_db_msg = LeaveRecord.update_local_db(self)
        if updated_db_msg == None:
            raise ReplyError(errors['NO_DEL_DATE'])
        self.content_sid = os.environ.get("LEAVE_NOTIFY_CANCEL_SID")
        self.set_cv_func = self.get_forward_CANCEL_LEAVE_cv
        self.forward_messages()
        return f"{updated_db_msg}, messages have been forwarded. Pending success..."
    
    @JobUser.loop_relations # just need to pass in the user when calling get_forward_leave_cv
    def get_forward_CANCEL_LEAVE_cv(self, relation):
        '''LEAVE_NOTIFY_CANCEL_SID'''

        return {
            '1': relation.alias,
            '2': self.user.alias,
            '3': self.original_job.leave_type.lower(),
            '4': f"{str(self.duration)} {'day' if self.duration == 1 else 'days'}",
            '5': print_all_dates(self.dates_to_update, date_obj=True)
        }
    
    # inherit
    # def handle_replied_future_results(self, future_results):

    # inherit
    # @overrides
    # def validate_complete(self):