from datetime import datetime, timedelta, date
from extensions import db, get_session
from constants import LeaveError, Error, LeaveType, LeaveIssue, leave_keywords, SelectionType, Decision, Intent, JobStatus, LeaveStatus, AuthorizedDecision, LeaveStateEnum
from dateutil.relativedelta import relativedelta
import os
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, join_with_commas_and, get_latest_date_past_9am, combine_with_key_increment
from overrides import overrides

from MessageLogger import setup_logger

from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUserInitial, JobUserInitial
from models.leave_records import LeaveRecord
import re
import traceback
from .utils_leave import dates
from sqlalchemy.types import Enum as SQLEnum
from enum import Enum

class JobLeave(JobUserInitial):
    __tablename__ = "job_leave"
    job_no = db.Column(db.ForeignKey("job_user_initial.job_no"), primary_key=True) # TODO on delete cascade?
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)
    auth_status = db.Column(SQLEnum(AuthorizedDecision), nullable=False)
    status = db.Column(SQLEnum(JobStatus), nullable=False)

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
        self.update_status(LeaveStateEnum.MESSAGE_RECEIVED) # calls self.get_dates
        
    ###############################
    # SETTING REDIS DATA
    ###############################

    def update_cache(self):
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
        
    def restore_cache(self, job_information, selection_type, selection): # TODO
        self.dates_to_update = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in job_information['dates']]
        self.duplicate_dates = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in job_information['duplicate_dates']]
        self.validation_errors = set([LeaveError(int(value)) for value in job_information.get('validation_errors')])
        if selection_type == SelectionType.LEAVE_TYPE:
            self.leave_type = selection

    # PIPELINE HELPER FUNCTION
    def update_status(self, new_status):
        self.status = new_status
        self.postprocess()

    ###########################
    # SECTION PREPROCESS
    ###########################

    def preprocess(self, message):
        if self.status == LeaveStateEnum.SERVER_ERROR:
            self.notify_error()

        method_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            LeaveStateEnum.MESSAGE_RECEIVED: self.get_dates,
            # LeaveStateEnum.DATES_NOT_FOUND: self.get_dates, # can be from initial message or selection
            LeaveStateEnum.LEAVE_TYPE_NOT_FOUND: self.get_leave_selection,
            LeaveStateEnum.PENDING_DECISION: self.get_decision,
            LeaveStateEnum.PENDING_AUTHORISATION: self.get_authorisation,
            LeaveStateEnum.LEAVE_CONFIRMED: self.get_selection_after_confirmed, # send update on db, start new thread for corwards callback
            LeaveStateEnum.LEAVE_CANCELLED: self.get_selection_after_cancelled,
            LeaveStateEnum.LEAVE_APPROVED: self.get_selection_after_approval,
            LeaveStateEnum.LEAVE_REJECTED: self.get_selection_after_rejection,
            LeaveStateEnum.REGEX_ERROR: self.get_selection_after_regex_error,
        }
        message = self.get_enum(message)
        action = method_map.get(self.status)
        if action:
            action(message)

    def get_dates(self, message): # MESSAGE WHILE MESSAGE_RECEIVED
        '''Generates the basic details of the MC, including the start, end and duration of MC'''
        
        print("Handling initial request")

        self.start_date = self.end_date = self.duration = None

        self.logger.info(f"User string in generate base: {message}")

        try:
            # self.duration is extracted duration
            if dates.duration_extraction(message):
                self.duration = int(dates.duration_extraction(message))

            duration_c = self.set_start_end_date() # checks for conflicts and sets the dates

            self.logger.info("start get_dates")
            
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

            # GET VALIDATION ERRORS FOR DATES
            self.validation_errors = set((*self.validate_start_date(), *self.validate_overlap()))

            if LeaveIssue.OVERLAP in self.validation_errors and LeaveIssue.LATE in self.validation_errors:
                if current_sg_time().date() in self.duplicate_dates:
                    self.validation_errors.discard(LeaveIssue.LATE)

            self.logger.info(f"ERRORS: {[err for err in self.validation_errors]}")

            self.update_status(LeaveStateEnum.DATES_FOUND)
                
        except DurationError as e:
            logging.error(f"error message is {e.message}")
            raise ReplyError(e.message)

    ###########################
    # GETTING CONFIRMATION
    ###########################

    def get_leave_selection(self, selection): # MESSAGE WHILE LEAVE_TYPE_NOT_FOUND
        print("Getting leave selection")
        if not isinstance(selection, LeaveType):
            raise ReplyError(Error.UNKNOWN_ERROR)

        self.leave_type = selection
        self.update_status(LeaveStateEnum.LEAVE_TYPE_FOUND)

    def get_decision(self, selection): # MESSAGE WHILE PENDING_DECISION
        print("Getting Decision")
        
        if isinstance(selection, Decision):
            if selection == Decision.CONFIRM:
                self.update_status(LeaveStateEnum.LEAVE_CONFIRMED)
            elif selection == Decision.CANCEL:
                self.update_status(LeaveStateEnum.REGEX_ERROR)
                raise ReplyError(LeaveError.REGEX)
        elif isinstance(selection, LeaveType):
            raise ReplyError() # TODO
        else:
            raise ReplyError()

    def get_authorisation(self, selection): # MESSAGE WHILE PENDING_AUTHORISATION
        print("Getting authorisation")

        if isinstance(selection, AuthorizedDecision):
            if selection == AuthorizedDecision.APPROVE:
                self.update_status(LeaveStateEnum.LEAVE_APPROVED)
            elif selection == AuthorizedDecision.REJECT:
                self.update_status(LeaveStateEnum.LEAVE_REJECTED)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(Error.PENDING_AUTHORISATION, job_status=None) # TODO job_status is now only for leave class?
        
        elif isinstance(selection, Decision):
            if selection == Decision.CANCEL: # TODO check for last confirm message?
                # TODO start cancel process while pending validation
                self.update_status(LeaveStateEnum.LEAVE_CANCELLED)
        else:
            raise ReplyError(Error.UNKNOWN_ERROR, job_status=None)
        
    def get_selection_after_cancelled(self, selection): # MESSAGE WHILE LEAVE_CANCELLED
        print("Handling selection after cancelled")

        if isinstance(selection, AuthorizedDecision):
            raise ReplyError(LeaveError.AUTHORISING_CANCELLED_MSG, job_status=None)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_CANCELLED, job_status=None) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        else:
            raise ReplyError(Error.UNKNOWN_ERROR, job_status=None)

    def get_selection_after_approval(self, selection): # MESSAGE WHILE LEAVE_APPROVED
        print("Handling selection after approval")

        if isinstance(selection, AuthorizedDecision) and selection == AuthorizedDecision.REJECT:
            self.update_status(LeaveStateEnum.LEAVE_REJECTED)

        elif isinstance(selection, Decision) and selection == Decision.CANCEL:
            self.update_status(LeaveStateEnum.LEAVE_CANCELLED)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_APPROVED, job_status=None) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        else:
            raise ReplyError(Error.UNKNOWN_ERROR, job_status=None)

    def get_selection_after_rejection(self, selection): # MESSAGE WHILE LEAVE_REJECTED
        print("Handling selection after rejection")

        if isinstance(selection, AuthorizedDecision) and selection == AuthorizedDecision.APPROVE:
            raise ReplyError(LeaveError.LEAVE_REJECTED, job_status=None)
        
        elif isinstance(selection, Decision) and selection == Decision.CANCEL:
            raise ReplyError(LeaveError.LEAVE_REJECTED, job_status=None)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_REJECTED, job_status=None) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        else:
            raise ReplyError(Error.UNKNOWN_ERROR, job_status=None)

    def get_selection_after_regex_error(self, selection):
        print("Handling selection after regex error")

        if isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_CANCELLED, job_status=None) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        elif selection == Decision.CONFIRM:
            raise ReplyError(Error.CONFIRMING_CANCELLED_MSG, job_status=None)
        else:
            raise ReplyError(Error.UNKNOWN_ERROR, job_status=None)

        
    ######################
    # SECTION POSTPROCESS
    ######################

    def postprocess(self):
        method_map = {
            LeaveStateEnum.DATES_FOUND: self.match_leave_type, # can be from initial message or selection
            LeaveStateEnum.LEAVE_TYPE_FOUND: self.send_decision,
            LeaveStateEnum.LEAVE_CONFIRMED: self.send_authorisation,
            LeaveStateEnum.LEAVE_APPROVED: self.notify_approval,
            LeaveStateEnum.LEAVE_REJECTED: self.notify_rejection,
            LeaveStateEnum.LEAVE_CANCELLED: self.notify_cancellation, # if cancelled then confirmed, raise error and set status to server error
            LeaveStateEnum.SERVER_ERROR: self.notify_error, # for dates not found, regex error. DONT SET TO SERVER ERROR IF COMPLETED, otherwise might not be able to reject
        }
        action = method_map.get(self.status)
        if action:
            action()

    def match_leave_type(self): # DATES_FOUND

        print("Getting leave type")

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

    ###########################
    # SENDING CONFIRMATION
    ###########################
    
    def send_decision(self): # LEAVE_TYPE_FOUND
        content_sid, cv = self.get_leave_confirmation_sid_and_cv()
        message_scheduler.add_to_queue(self.user.sg_number, (content_sid, cv))

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
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_3_ISSUES_SID")
        elif errors == {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} or errors == {LeaveIssue.OVERLAP, LeaveIssue.LATE}:
            issues = {
                2: self.print_overlap_dates(),
                3: LeaveIssue.UPDATED.value if {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif errors == {LeaveIssue.UPDATED, LeaveIssue.LATE}:
            issues = {
                2: LeaveIssue.UPDATED.value,
                3: LeaveIssue.LATE.value
            }
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif {LeaveIssue.OVERLAP} or errors == {LeaveIssue.UPDATED} or errors == {LeaveIssue.LATE}:
            issues = {
                2: self.print_overlap_dates() if errors == {LeaveIssue.OVERLAP} else LeaveIssue.UPDATED.value if errors == {LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_1_ISSUE_SID")
        elif errors == set():
            issues = {}
            content_sid = os.environ.get("LEAVE_CONFIRMATION_CHECK_SID")
        else:
            self.logger.error(f"UNCAUGHT errors IN CV: {errors}")
            raise ReplyError(Error.UNKNOWN_ERROR)
        
        cv = json.dumps(combine_with_key_increment(base_cv, issues))

        return content_sid, cv
    
    def set_dates_str(self, mark_late):
        dates_str = print_all_dates(self.dates_to_update, date_obj=True)

        if mark_late:
            cur_date = current_sg_time().date()
            cur_date_str = cur_date.strftime('%d/%m/%Y')

            if get_latest_date_past_9am() > cur_date:
                dates_str = re.sub(cur_date_str, cur_date_str + ' (*LATE*)', dates_str)

        return dates_str
    
    def print_overlap_dates(self):
        return LeaveIssue.OVERLAP.value + print_all_dates(self.duplicate_dates, date_obj=True)

    def send_authorisation(self): # LEAVE_CONFIRMED
        print("Sending authorisation")

        # initilalise leave database
        updated_db_msg = LeaveRecord.add_leaves(self)
        message = # TODO INSERT THE SID TO SEND TO RO
        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO RO

        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO USER

        # send authorisation request

    def forward_messages(self):
        super().forward_messages() # TODO
        print("Forwarding messages")

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

    def notify_approval(self): # LEAVE_APPROVED
        print("Notifying approval")

        updated_db_msg = self.approve_leaves()

        self.content_sid = os.environ.get("LEAVE_NOTIFY_APPROVAL_SID") # TODO
        self.cv_list = self.get_forward_leave_cv(mark_late=True)
        self.forward_messages() # SEND TO SLs

        message = f"{updated_db_msg}, messages have been forwarded. Pending success..."
        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO USER

    def notify_rejection(self): # LEAVE_REJECTED
        print("Notifying rejection")

        updated_db_msg = self.reject_leaves()

        if self.approval_process: # TODO CHECK IF FORWARD MSG HAS BEEN SENT, MIGHT HAVE TO FORWARD MSGES
            self.content_sid = os.environ.get("LEAVE_NOTIFY_REJECTION_SID") # TODO
            self.cv_list = self.get_forward_leave_cv()
            self.forward_messages() # SEND TO SLs

        message = f"{updated_db_msg}, messages have been forwarded. Pending success..."
        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO USER

    def notify_cancellation(self): # LEAVE_CANCELLED
        print("Notifying cancellation")

        updated_db_msg = self.cancel_leaves()

        if self.approval_process: # TODO CHECK IF FORWARD MSG HAS BEEN SENT, MIGHT HAVE TO FORWARD MSGES
            self.content_sid = os.environ.get("LEAVE_NOTIFY_REJECTION_SID") # TODO
            self.cv_list = self.get_forward_leave_cv()
            self.forward_messages() # SEND TO SLs

        message = f"{updated_db_msg}, messages have been forwarded. Pending success..."
        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO USER
    
    ##########################
    # HANDLING SUBJOBS
    ##########################
    
    def cancel_leaves(self): # only find PENDING and APPROVED
        records = LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED])
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL)
        return self.update_leaves(records, LeaveStatus.CANCELLED)

    def approve_leaves(self): # only find PENDING (cannot approve after reject)
        records = LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED, LeaveStatus.APPROVED])
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL) # TODO
        return self.update_leaves(records, LeaveStatus.APPROVED)
    
    def reject_leaves(self): # only find PENDING and APRROVED
        records = LeaveRecord.get_records(self, ignore_statuses=[LeaveStatus.CANCELLED, LeaveStatus.ERROR, LeaveStatus.REJECTED])
        if not records or len(records) == 0:
            raise ReplyError(LeaveError.NO_DATES_TO_DEL) # TODO
        return self.update_leaves(records, LeaveStatus.REJECTED)

    def update_leaves(self, records, status):
        updated_db_msg = LeaveRecord.update_leaves(self, records, status)
        self.content_sid = os.environ.get("LEAVE_NOTIFY_CANCEL_SID")
        self.cv_list = self.get_forward_leave_cv()
        self.forward_messages()
        return f"{updated_db_msg}, messages have been forwarded. Pending success..."

    ##########################
    # HANDLING INCOMING MSGES
    ##########################

    def cleanup_on_error(self):
        LeaveRecord.update_local_db(self, status=LeaveStatus.ERROR)
        pass

    def handle_job_expiry(self):
        pass

    def notify_error(self):
        print("Handling server error")
        self.cleanup_on_error()
        message = "Something went wrong, please try again!" # TODO
        message_scheduler.add_to_queue(self.user.sg_number, message) # SEND TO USER

    def get_selection_after_confirmed(self, selection): # MESSAGE WHILE LEAVE_CONFIRMED
        print("Handling selection after confirmed")
        if selection in Decision._value2member_map_:
            decision = Decision(selection)
        elif selection in LeaveType._value2member_map_:
            raise ReplyError() # TODO
        else:
            raise ReplyError()

        if decision == Decision.CONFIRM:
            self.update_status(LeaveStateEnum.LEAVE_CONFIRMED)
        elif decision == Decision.CANCEL:
            self.update_status(LeaveStateEnum.REGEX_ERROR)
            raise ReplyError(LeaveError.REGEX)
    
    ###################
    # HELPER FUNCTIONS
    ###################

    def get_enum(self, message):
        if message in Decision._value2member_map_:
            return Decision(message)
        elif message in LeaveType._value2member_map_:
            return LeaveType(message) # TODO
        elif message in AuthorizedDecision._value2member_map_:
            return AuthorizedDecision(message)
        else:
            return message

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

