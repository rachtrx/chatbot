from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import desc, JSON
from typing import List
import uuid
from constants import intents, errors, DURATION_CONFLICT, PENDING_USER_REPLY, CONFIRM, CANCEL, FAILED, OK, CHANGED, CANCELLED, PENDING
import re
from dateutil.relativedelta import relativedelta
import os
import uuid
import logging
import traceback
import json
from utilities import current_sg_time, print_all_dates, print_relations_list
from azure.mc.upload import SpreadsheetManager
from azure.utils import loop_mc_files, AzureSyncError
import time
from overrides import overrides

from logs.config import setup_logger

from constants import intents, MAX_UNBLOCK_WAIT

from models.exceptions import ReplyError, DurationError
from models.users import User
from models.messages import MessageForward, MessageConfirm

from ..job import Job
from .utils import dates, get_cv


class JobMc(Job):
    __tablename__ = "job_mc"
    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True) # TODO on delete cascade?
    _start_date = db.Column(db.String(20), nullable=True)
    _end_date = db.Column(db.String(20), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    _new_monthly_dates = db.Column(JSON, nullable=True)
    _current_dates = db.Column(JSON, nullable=True)
    azure_complete = db.Column(db.Boolean, default=False, nullable=True)
    forwards_complete = db.Column(db.Boolean, default=False, nullable=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_mc"
    }

    logger = setup_logger('models.job_mc')

    def __init__(self, name):
        super().__init__(name)
        self.new_monthly_dates = {}
        self.current_dates = []
        db.session.commit()

    @property
    def start_date(self):
        return datetime.strptime(self._start_date, "%d/%m/%Y").date() if self._start_date is not None else None

    @start_date.setter
    def start_date(self, value):
        self._start_date = datetime.strftime(value, "%d/%m/%Y")

    @property
    def end_date(self):
        return datetime.strptime(self._end_date, "%d/%m/%Y").date() if self._end_date is not None else None

    @end_date.setter
    def end_date(self, value):
        self._end_date = datetime.strftime(value, "%d/%m/%Y")

    @property
    def new_monthly_dates(self):
        return json.loads(self._new_monthly_dates) if self._new_monthly_dates is not None else None

    @new_monthly_dates.setter
    def new_monthly_dates(self, value):
        self._new_monthly_dates = json.dumps(value)

    @property
    def current_dates(self):
        return json.loads(self._current_dates) if self._current_dates is not None else None
    
    @current_dates.setter
    def current_dates(self, value):
        self._current_dates = json.dumps(value)

    @overrides
    def validate_confirm_message(self):

        decision = self.current_msg.decision
        raise_unknown_error = False

        self.logger.info(f"Status: {self.status}, decision: {decision}")

        if decision != CONFIRM and decision != CANCEL:
            logging.error(f"UNCAUGHT DECISION {decision}")
            raise_unknown_error = True

        if decision == CANCEL:

            if self.status != OK or self.status != PENDING_USER_REPLY:
                raise_unknown_error = True

            self.commit_cancel()

            if self.status == OK:

                latest_confirm_msg = MessageConfirm.get_latest_confirm_message(self.job_no)
                if self.current_msg.ref_msg_sid != latest_confirm_msg.ref_msg_sid:
                    raise ReplyError(errors['NOT_LAST_MSG'], job_status=None)
                
                is_blocking = True

                for _ in range(MAX_UNBLOCK_WAIT):
                    if not self.user.is_blocking:
                        is_blocking = False
                        break
                    time.sleep(1)

                if is_blocking:
                    raise_unknown_error = True
                # OK
                
            else: # PENDING_USER_REPLY
                self.logger.info("cancelling MC due to wrong date")
                
                raise ReplyError(errors['WRONG_DATE'], intent=intents['TAKE_MC'])
        
        else: # CONFIRM

            if self.status == PENDING_USER_REPLY:
                # confirm MC
                pass # OK

            elif self.is_cancelled:
                raise ReplyError(errors['CONFIRMING_CANCELLED_MSG'])

            else: # TODO IMPT need to wait awhile first!
                raise_unknown_error = True
        
        if raise_unknown_error:
            raise ReplyError(errors['UNKNOWN_ERROR'])

        self.commit_status(PENDING)
        return


    @overrides
    def handle_user_reply_action(self):
        self.forward_messages()
        reply = self.update_azure()
        return reply
    
    @overrides
    def entry_action(self):
        statuses = self.generate_base()
        reply = self.generate_msg_from_status(statuses)
        self.is_expecting_user_reply = True
        return reply

    @overrides
    def check_for_complete(self):
        if self.status == OK:
            return
        
        self.logger.info(f"user: {self.user.name}, messages: {self.messages}")

        last_message_replied = self.all_messages_replied()
            
        if self.azure_complete and self.forwards_complete and last_message_replied:
            self.logger.info("job complete")
            self.commit_status(OK) if self.cancelled is False else self.commit_status(CANCELLED)
            self.user.is_blocking = False
            db.session.commit()

    def generate_base(self):
        '''Generates the basic details of the MC, including the start, end and duration of MC'''

        try:
            if not self.new_monthly_dates:

                user_str = self.current_msg.body

                # self.duration is extracted duration
                self.duration = int(dates.duration_extraction(user_str)) if dates.duration_extraction(user_str) else None
                duration_c = self.set_start_end_date(user_str) # checks for conflicts and sets the dates

                self.logger.info("start generate_base")
                
                if duration_c:
                    # if there are specified dates and no duration
                    self.logger.info(f"{self.end_date}, {self.duration}, {duration_c}, {self.start_date}")
                    if self.duration == None:
                        self.duration = duration_c
                    # if there are specified dates and duration is wrong
                    elif self.duration and self.duration != duration_c:

                        body = f'The duration from {self.start_date} to {self.end_date} ({duration_c}) days) do not match with {self.duration} days. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

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
            
                try:
                    overlap_status = self.validate_overlap()
                except AzureSyncError as e:
                    self.logger.info(e.message)
                    body = f"Hi {self.user.name}, we were unable to retrieve the current MC records. Please try again. If the problem persists, please check with the ICT department"
                    raise ReplyError(body, intent=intents['TAKE_MC'])

                self.logger.info(f"Dates validated")
                
                return start_date_status, overlap_status
                
        except DurationError as e:
            raise ReplyError(e.message, intent=intents['TAKE_MC'], job_status=DURATION_CONFLICT)
        
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

        print(f'duration: {duration}')

        return duration
        
    def validate_start_date(self):
        '''Checks if start date is valid, otherwise tries to set the start date and duration'''
        earliest_possible_date = current_sg_time().date()
        self.logger.info(f"current time is later than 8am: {current_sg_time() > current_sg_time(hour_offset=8)}")
        self.logger.info(f"{current_sg_time()}, {current_sg_time(hour_offset=8)}")
        if current_sg_time() > current_sg_time(hour_offset=8):
            earliest_possible_date += timedelta(days=1)
        
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
                db.session.commit()
                status = CHANGED
        else:
            status = OK
        
        return status

        
    def validate_overlap(self):
        '''
        checks if the dates overlap, sets self.duplicate_dates, self.non_duplicate_dates, and self._new_monthly_dates
        Sets the dates that do not overlap as self._new_monthly_dates and calculates the duration
        '''
        # IMPT This is the very last validation. If the user confirms, it bypasses another validation check!
        self.check_for_duplicates() # sets the duplicate dates

        if len(self.duplicate_dates) != 0 and len(self.non_duplicate_dates) != 0:
            self.logger.info("duplicates but can be fixed")
            status = CHANGED
        elif len(self.duplicate_dates) != 0:
            self.logger.info("duplicates cannot be fixed")
            raise DurationError(errors["ALL_DUPLICATE_DATES"])
        else:
            status = OK
        
        return status

    def check_for_duplicates(self):

        def daterange():
            for n in range(self.duration):
                yield self.start_date + timedelta(n)

        self.monthly_dates = {}

        for date in daterange():
            month_key = date.strftime('%B-%Y')
            if month_key not in self.monthly_dates:
                self.monthly_dates[month_key] = []
            self.monthly_dates[month_key].append(date)

        self.duplicate_dates = []
        self.non_duplicate_dates = []
        new_monthly_dates = self.new_monthly_dates if self.new_monthly_dates is not None else {}

        for mmyy, dates_list in self.monthly_dates.items():
            self.logger.info(f"starting manager for {mmyy}, dates list is {dates_list}")
            manager = SpreadsheetManager(mmyy, self.user)
            date_data = manager.check_duplicate_dates(dates_list)
            new_duplicates, new_non_duplicates = date_data

            self.logger.info(f"duplicate dates: {new_duplicates}, non duplicates: {new_non_duplicates}")

            # Store the filtered details back into a new dictionary
            if len(new_non_duplicates) > 0:
                new_monthly_dates[mmyy] = [datetime.strftime(date, "%d/%m/%Y") for date in new_non_duplicates]

            # these are the arrays to inform the user about overlapping dates, they are not saved in the database
            self.duplicate_dates.extend(new_duplicates)
            self.non_duplicate_dates.extend(new_non_duplicates)

        self.new_monthly_dates = new_monthly_dates
        self.duration = len(self.non_duplicate_dates)
        db.session.commit()

        # self.logger.info(self.new_monthly_dates)
        # self.logger.info(self.duplicate_dates)
        # self.logger.info(self.non_duplicate_dates)

    def generate_msg_from_status(self, statuses):
        '''self always has a job that is an JobMc object'''

        start_date_status, overlap_status = statuses

        if overlap_status == CHANGED and start_date_status == CHANGED:
            cv_func = get_cv.get_later_start_date_and_overlap_confirm_mc_cv
            content_sid = os.environ.get("MC_LATER_START_DATE_AND_OVERLAP_CONFIRMATION_CHECK_SID")
        if overlap_status == CHANGED: # check that it is an mc message
            cv_func = get_cv.get_overlap_confirm_mc_cv
            content_sid = os.environ.get("MC_OVERLAP_CONFIRMATION_CHECK_SID")
        elif start_date_status == CHANGED:
            cv_func = get_cv.get_later_start_date_confirm_mc_cv
            content_sid = os.environ.get("MC_LATER_START_DATE_CONFIRMATION_CHECK_SID")
        elif start_date_status == OK and overlap_status == OK: # status is OK
            cv_func = get_cv.get_confirm_mc_cv
            content_sid = os.environ.get("MC_CONFIRMATION_CHECK_SID")
        else:
            self.logger.error(f"UNCAUGHT STATUS {start_date_status}, {overlap_status}")
            
        content_variables = self.user.get_cv_many_relations(cv_func, self)
        
        if content_variables is None: # if no relations
            raise ReplyError(errors['NO_RELATIONS'], intent=intents['TAKE_MC'])
        else:
            return content_sid, content_variables
        
    
    def set_start_end_date(self, message):
        '''This function takes in a mc_message and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = dates.named_month_extraction(message)
        ddmm_start, ddmm_end = dates.named_ddmm_extraction(message)
        print(f'ddmm_end: {ddmm_end}')
        day_start, day_end = dates.named_day_extraction(message)
        
        start_dates = [date for date in [named_month_start, ddmm_start, day_start] if date is not None]
        end_dates = [date for date in [named_month_end, ddmm_end, day_end] if date is not None]

        self.logger.info(f"{start_dates}, {end_dates}")

        if len(start_dates) > 1:

            body = f'Conflicting start dates {", ".join(str(date) for date in start_dates)}. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

            raise DurationError(body)
        if len(end_dates) > 1:
            
            body = f'Conflicting end dates {", ".join(str(date) for date in end_dates)}. Please send another message in the form "From dd/mm to dd/mm" to indicate the MC dates. Thank you!'

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

    
    ##############################
    # FORWARDING THE MC MESSAGE
    ##############################

    def forward_messages(self):
        
        if self.current_msg.decision == CONFIRM:
            content_sid = os.environ.get("MC_NOTIFY_SID")

        else: 
            content_sid = os.environ.get("MC_NOTIFY_CANCEL_SID") # USER CANCELS
        
        cv_and_relations_list = MessageForward.get_cv_and_relations_list(self.user, MessageForward.get_forward_mc_cv, self)

        self.logger.info(f"forwarding messages with this cv list: {cv_and_relations_list}")

        MessageForward.forward_template_msges(cv_and_relations_list, content_sid, self)
        
    def update_azure(self):

        decision = self.current_msg.decision

        # upload to azure
        try:
            current_dates = []

            if decision == CANCEL:
                del_dates = []

            mmyy_arr = loop_mc_files()
            # self.logger.info(f"mmyy_arr: {mmyy_arr}")

            # check every 
            for mmyy, dates_list in self.new_monthly_dates.items():
                self.logger.info(f"mmyy: {mmyy}")

                manager = SpreadsheetManager(mmyy, self.user)
                current_mc_dates = manager.get_unique_current_dates()
                current_dates_array = [date.strftime('%d/%m/%Y') for date in current_mc_dates] if len(current_mc_dates) > 0 else []
                # dont extend yet since cancel decision needs to slice the array
                

                if decision == CONFIRM:
                    manager.upload_data(dates_list)
                    # The call to get the dates often happen too fast, so we manually add the dates
                    current_dates.extend(dates_list)
                elif decision == CANCEL:
                    del_mc_dates = manager.delete_data(dates_list)
                    del_dates.extend(del_mc_dates)
                    current_dates_array = [date for date in current_dates_array if date not in del_mc_dates]

                current_dates.extend(current_dates_array)
                
                if mmyy in mmyy_arr:
                    mmyy_arr.remove(mmyy)
                    self.logger.info(f"removing {mmyy} from the array")

            
            for mmyy in mmyy_arr:
                manager = SpreadsheetManager(mmyy, self.user)
                current_mc_dates = manager.get_unique_current_dates()
                current_dates_array = [date.strftime('%d/%m/%Y') for date in current_mc_dates] if len(current_mc_dates) > 0 else []
                current_dates.extend(current_dates_array)
                
            self.current_dates = current_dates
            self.azure_complete = True
            db.session.commit()

            if decision == CONFIRM:
                body = f"Hi {self.user.name}, your future MC records have been updated. You are on MC on {print_all_dates(self.current_dates)}"
            else:
                body = f"Hi {self.user.name}, "
                if len(del_dates) > 0:
                    body += f"Your future MC records have been deleted for {print_all_dates(del_dates)}. "
                if len(self.current_dates) > 0:
                    body += f"You are on MC on {print_all_dates(self.current_dates)}."
                else:
                    body += f"There are no other MC records under your name."

            return body

        except AzureSyncError as e:
            self.logger.info(e.message)
            body = f"Hi {self.user.name}, your MC records FAILED to update. Please try again. If the problem persists, please check with the ICT department"
            raise ReplyError(body, intent=intents['TAKE_MC'])
    

    