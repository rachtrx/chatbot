from datetime import datetime, timedelta, date
from extensions import db, get_session
from constants import LeaveError, Error, LeaveType, LeaveIssue, leave_keywords, SelectionType, Decision, Intent, JobStatus, LeaveStatus, AuthorizedDecision
from dateutil.relativedelta import relativedelta
import os
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, join_with_commas_and, get_latest_date_past_9am, combine_with_key_increment
from overrides import overrides

from MessageLoggersetup_logger

from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUserInitial, JobUserInitial
from models.leave_records import LeaveRecord
import re
import traceback
from .utils_leave import dates
from sqlalchemy.types import Enum as SQLEnum

class JobLeave(JobUserInitial):
    __tablename__ = "job_leave"
    job_no = db.Column(db.ForeignKey("job_user_initial.job_no"), primary_key=True) # TODO on delete cascade?
    
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)
    auth_status = db.Column(SQLEnum(AuthorizedDecision), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "job_leave"
    }

    logger = setup_logger('models.job_leave')
    errors = LeaveError
    cancel_intent = Intent.CANCEL_LEAVE

    def __init__(self, name):
        super().__init__(name)
        self.duplicate_dates = []
        self.validation_errors = set()
        self.auth_status = False
        
    ###############################
    # SETTING REDIS DATA
    ###############################

    def set_cache_data(self):
        if getattr(self, 'dates_to_update'):
            return {
                # actual job information
                # created by generate base
                "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
                "duplicate_dates": [date.strftime("%d-%m-%Y") for date in self.duplicate_dates],
                # returned by generate base
                "validation_errors": [error.value for error in list(self.validation_errors)],
                # can be blank after genenrate base
                "leave_type": getattr(self, 'leave_type')
            }
        else:
            return None
    
    ###############################
    # RETRIEVING REDIS DATA
    ###############################
        
    def update_info(self, job_information, selection_type, selection): # TODO
        self.dates_to_update = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in job_information['dates']]
        self.duplicate_dates = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in job_information['duplicate_dates']]
        self.validation_errors = set([LeaveError(int(value)) for value in job_information.get('validation_errors')])
        if selection_type == SelectionType.LEAVE_TYPE:
            self.leave_type = selection
        
    ##########################
    # HANDLING SUBJOBS
    ##########################
    
    def get_cancel_details(self): # only find PENDING and APPROVED
        return LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED])
    
    def get_approve_details(self): # only find PENDING (cannot approve after reject)
        return LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED, LeaveStatus.APPROVED])

    def get_reject_details(self): # only find PENDING and APRROVED
        return LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED])

    def update_leaves(self, job, records, status):
        updated_db_msg = LeaveRecord.update_leaves(self, records, job, status)
        job.content_sid = os.environ.get("LEAVE_NOTIFY_CANCEL_SID")
        job.cv_list = self.get_forward_leave_cv()
        job.forward_messages()
        return f"{updated_db_msg}, messages have been forwarded. Pending success..."

    
    def handle_cancellation(self, cancel_job, records):
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL)
        
        return self.update_leaves(cancel_job, records, LeaveStatus.CANCELLED)
    
    def handle_approve(self, approval_job, records): 
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL)
        
        return self.update_leaves(approval_job, records, LeaveStatus.APPROVED)

    def handle_reject(self, rejection_job, records):
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL)
        
        return self.update_leaves(rejection_job, records, LeaveStatus.APPROVED)

    ##########################
    # HANDLING INCOMING MSGES
    ##########################
    
    def handle_initial_request(self, user_str, selection=None):
        '''Returns Reply to Initial Message'''

        self.user_str = user_str

        if not isinstance(selection, LeaveType): # retry message
            raise ReplyError(Error.UNKNOWN_ERROR)

        else: # first message
            self.generate_base()
            self.set_validation_errors()

            # CATCH LEAVE TYPE ERRORS
            self.leave_type = self.set_leave_type()

        self.selection_type = SelectionType.DECISION
        self.get_leave_confirmation_sid_and_cv()
        return (self.content_sid, self.cv)
    
    def handle_confirm_decision(self):
        '''Decision.CONFIRM: if it has the user string, its the first msg, or a retry message. user_str attribute it set either in update_info or during job initialisation'''

        # these 2 functions are implemented with method overriding
        self.validate_confirm_message() # checks for ReplyErrors based on state

        updated_db_msg = LeaveRecord.add_leaves(self)
        self.content_sid = os.environ.get("LEAVE_NOTIFY_SID")
        self.cv_list = self.get_forward_leave_cv(mark_late=True)
        self.forward_messages()
        return f"{updated_db_msg}, messages have been forwarded. Pending success..."
    
    def handle_cancellation_before_authorisation(self): # TODO
        pass

    def cleanup_on_error(self):
        LeaveRecord.update_local_db(self, status=LeaveStatus.ERROR)
        pass

    def set_validation_errors(self):
        all_errors = set((*self.validate_start_date(), *self.validate_overlap()))

        if LeaveIssue.OVERLAP in all_errors and LeaveIssue.LATE in all_errors:
            if current_sg_time().date() in self.duplicate_dates:
                all_errors.discard(LeaveIssue.LATE)

        self.logger.info(f"ERRORS: {[err for err in all_errors]}")
        
        self.validation_errors = all_errors
    
    def set_leave_type(self):
        leave_keyword_patterns = re.compile(leave_keywords, re.IGNORECASE)
        leave_match = leave_keyword_patterns.search(self.user_str)

        if leave_match:
            matched_term = leave_match.group(0) if leave_match else None
            for leave_type, phrases in leave_keywords.items():
                if matched_term.lower() in [phrase.lower() for phrase in phrases]:
                    return leave_type
            # UNKNOWN ERROR... keyword found but couldnt lookup
        
        content_sid = os.environ.get('SELECT_LEAVE_TYPE_SID')
        self.selection_type = SelectionType.LEAVE_TYPE
        cv = None
        raise ReplyError(err_message=(content_sid, cv), job_status=None)
    
    @overrides
    def validate_complete(self):
        self.logger.info(f"user: {self.user.name}, messages: {self.messages}")
        
        if self.local_db_updated and self.all_messages_successful():
            last_message_replied =  # IMPT check for any double selections before unblocking
            if last_message_replied:
                self.logger.info("all messages successful")
                return True
        self.logger.info("all messages not successful")
        return False

    ###########################
    # SECTION ENTRY JobStatus
    ###########################

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

                    body = f'The duration from {datetime.strftime(self.start_date, "%d/%m/%Y")} to {datetime.strftime(self.end_date, "%d/%m/%Y")} ({duration_c}) days) do not match with {self.duration} days. Please send another message with the form "from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

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
                    raise DurationError(Error.DATES_NOT_FOUND)
            
            self.logger.info(f"{self.end_date}, {self.duration}, {duration_c}, {self.start_date}")
                
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

            body = f'Conflicting start dates {join_with_commas_and(datetime.strptime(date, "%d/%m/%Y") for date in start_dates)}. Please send another message with the form "from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise DurationError(body)
        if len(end_dates) > 1:
            
            body = f'Conflicting end dates {join_with_commas_and(datetime.strptime(date, "%d/%m/%Y") for date in end_dates)}. Please send another message with the form "from dd/mm to dd/mm" to indicate the MC dates. Thank you!'

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
        '''Checks if start date is valid, otherwise tries to set the start date and duration'''
        errors = []
        session = get_session()
        cur_sg_date = current_sg_time().date()
        earliest_possible_date = get_latest_date_past_9am()
        
        self.logger.info(earliest_possible_date)
        self.logger.info(f"{self.start_date}, {self.end_date}")
        # if end date is earlier than today, immediately reject
        if self.end_date < cur_sg_date:
            self.logger.info("date is too early cannot be fixed")
            body = f"Hi {self.user.alias}, I am no longer able to add your leave if you take it before today, sorry about the inconvenience."
            raise DurationError(body)
        # the start date is before today, but end date is at least today
        elif self.start_date < earliest_possible_date:
            # if start date is before today, definitely need to reset it to at least today
            if self.start_date < cur_sg_date:
                self.logger.info("date is too early but can be fixed")
                self.start_date = cur_sg_date
                self.duration = (self.end_date - self.start_date).days + 1
                session.commit()
                logging.info(f"committed in validate_start_date in session {id(session)}")
                errors.append(LeaveIssue.UPDATED)

            # the start date is now at least today, but we need to inform the user if it is already past 9am
            if earliest_possible_date > cur_sg_date:
                errors.append(LeaveIssue.LATE)
        
        return errors

        
    def validate_overlap(self):
        '''
        checks if the dates overlap, sets self.duplicate_dates, self.dates_to_update, and self.duration
        '''
        # IMPT This is the very last validation. If the user confirms, it bypasses another validation check!
        errors = []
        
        self.check_for_duplicates() # sets the duplicate dates

        if len(self.duplicate_dates) != 0 and len(self.dates_to_update) != 0:
            self.logger.info("duplicates but can be fixed")
            errors.append(LeaveIssue.OVERLAP)
        elif len(self.duplicate_dates) != 0:
            self.logger.info("duplicates cannot be fixed")
            raise DurationError(errors["ALL_DUPLICATE_DATES"])
        else:
            pass
        
        return errors

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
    
    #######################
    # SECTION CONFIRMATION 
    #######################

    @overrides
    def validate_selection_message(self, selection):
        pass
        
    ###################
    # SECTION AUTHORISATION
    ###################
    def approve(self):
        pass

    def reject(self):
        pass

    def handle_job_expiry(self):
        pass

    ##########################
    # SECTION UPDATE DATABASE
    ##########################


    #################################
    # CV TEMPLATES FOR MANY MESSAGES
    #################################
        
    def set_dates_str(self, mark_late):
        dates_str = print_all_dates(self.dates_to_update, date_obj=True)

        if mark_late:
            cur_date = current_sg_time().date()
            cur_date_str = cur_date.strftime('%d/%m/%Y')

            if get_latest_date_past_9am() > cur_date:
                dates_str = re.sub(cur_date_str, cur_date_str + ' (*LATE*)', dates_str)

        return dates_str

    def get_leave_confirmation_sid_and_cv(self):

        errors = self.validation_errors

        base_cv = {
            1: self.user.alias,
            2: self.leave_type.name.lower(),
            3: self.set_dates_str(),
            4: str(len(self.dates_to_update)),
            5: self.print_relations_list(),
            6: str(Decision.CONFIRM),
            7: str(Decision.CANCEL)
        }

        if errors == {LeaveIssue.OVERLAP, LeaveIssue.UPDATED, LeaveIssue.LATE}:
            issues = {
                2: self.print_overlap_dates(),
                3: LeaveIssue.UPDATED.value,
                4: LeaveIssue.LATE.value
            }
            self.content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_3_ISSUES_SID")
        elif errors == {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} or errors == {LeaveIssue.OVERLAP, LeaveIssue.LATE}:
            issues = {
                2: self.print_overlap_dates(),
                3: LeaveIssue.UPDATED.value if {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            self.content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif errors == {LeaveIssue.UPDATED, LeaveIssue.LATE}:
            issues = {
                2: LeaveIssue.UPDATED.value,
                3: LeaveIssue.LATE.value
            }
            self.content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif {LeaveIssue.OVERLAP} or errors == {LeaveIssue.UPDATED} or errors == {LeaveIssue.LATE}:
            issues = {
                2: self.print_overlap_dates() if errors == {LeaveIssue.OVERLAP} else LeaveIssue.UPDATED.value if errors == {LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            self.content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_1_ISSUE_SID")
        elif errors == set():
            issues = {}
            self.content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_SID")
        else:
            self.logger.error(f"UNCAUGHT errors IN CV: {errors}")
            raise ReplyError(Error.UNKNOWN_ERROR)
        
        self.cv = json.dumps(combine_with_key_increment(base_cv, issues))
    
    def print_overlap_dates(self):
        return LeaveIssue.OVERLAP.value + print_all_dates(self.duplicate_dates, date_obj=True)

    @JobUserInitial.loop_relations # just need to pass in the user when calling get_forward_leave_cv
    def get_forward_leave_cv(self, relation, mark_late=False):
        '''LEAVE_NOTIFY_SID and LEAVE_NOTIFY_CANCEL_SID; The decorator is for SENDING MESSAGES TO ALL RELATIONS OF ONE PERSON'''
        duration = len(self.dates_to_update)
        return {
            '1': relation.alias,
            '2': self.user.alias,
            '3': self.leave_type.lower(),
            '4': f"{str(duration)} {'day' if duration == 1 else 'days'}",
            '5': self.set_dates_str(mark_late)
        }