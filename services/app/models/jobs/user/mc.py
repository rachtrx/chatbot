from datetime import datetime, timedelta, date
from extensions import db
from sqlalchemy import JSON
from constants import errors, PENDING_USER_REPLY, CONFIRM, CANCEL, OK, CHANGED, SERVER_ERROR, messages
from dateutil.relativedelta import relativedelta
import os
import uuid
import logging
import json
import threading
from utilities import current_sg_time, print_all_dates, run_new_context, join_with_commas_and, get_latest_date_past_8am, get_session
from azure.sheet_manager import SpreadsheetManager
from azure.utils import loop_mc_files, AzureSyncError
from overrides import overrides

from logs.config import setup_logger

from models.exceptions import ReplyError, DurationError
from models.jobs.user.abstract import JobUser
from models.mc_records import McRecord
from models.messages.sent import MessageSent

from .utils_mc import dates, get_cv
from concurrent.futures import ThreadPoolExecutor, as_completed, wait


class JobMc(JobUser):
    __tablename__ = "job_mc"
    job_no = db.Column(db.ForeignKey("job_user.job_no"), primary_key=True) # TODO on delete cascade?
    _start_date = db.Column(db.String(20), nullable=True)
    _end_date = db.Column(db.String(20), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    _dates_to_update = db.Column(JSON, nullable=True)
    azure_status = db.Column(db.Integer, default=None, nullable=True)
    forwards_status = db.Column(db.Integer, default=None, nullable=True)
    local_db_updated = db.Column(db.Boolean(), nullable=False)
    leave_type = db.Column(db.String(20), nullable=False)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_mc"
    }

    logger = setup_logger('models.job_mc')

    def __init__(self, name, leave_type):
        super().__init__(name)
        self.new_monthly_dates = {}
        self.leave_type = leave_type
        self.local_db_updated = False
    
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
    def dates_to_update(self):
        if self._dates_to_update is not None:
            dates_list = json.loads(self._dates_to_update)
            if isinstance(dates_list, (list, tuple, set)):
                return [datetime.strptime(date, "%d/%m/%Y").date() for date in dates_list]
        return None

    @dates_to_update.setter
    def dates_to_update(self, dates):
        dates = [datetime.strftime(date, "%d/%m/%Y") for date in dates]
        self._dates_to_update = json.dumps(dates)

    @property
    def new_dates(self):
        '''self.dates_to_update may return [], so dont index it'''
        dates = {} 
        for date in self.dates_to_update:
            key = date.strftime('%B-%Y')
            if key not in dates:
                dates[key] = []
            dates[key].append(date)

        return dates

    def reset_complete_conditions(self):
        session = get_session()
        self.azure_status = None
        self.forwards_status = None
        session.commit()

    @overrides
    def validate_confirm_message(self):

        session = get_session()

        decision = self.current_msg.decision

        self.logger.info(f"Status: {self.status}, decision: {decision}")

        if self.end_date < get_latest_date_past_8am() and decision == CANCEL:
            raise ReplyError(errors['NO_DEL_DATE'])

        if not self.user.is_blocking: # job is COMPLETED/FAILED
            self.validate_confirmation_again(decision)
        
        elif self.user.is_blocking and self.status != PENDING_USER_REPLY: # other button had been pressed or another job in progress, but the job is no longer pending user reply
            # refreshing the object 4 lines below can lose the current_msg, so save the msg first
            temp_msg = self.current_msg
            is_blocking = self.user.wait_for_unblock()
            if not is_blocking:
                session.commit()
                self.current_msg = temp_msg
                logging.error(f"TRYING AGAIN {self.user.is_blocking}, {self.status}, {decision}")
                self.validate_confirmation_again(decision)
            else:
                logging.error(f"{self.user.is_blocking}, {self.status}, {decision}")
                raise ReplyError(errors['UNKNOWN_ERROR']) # blocking

        elif self.user.is_blocking: # blocking and pending user reply

            if decision == CANCEL:
                self.logger.info("cancelling MC due to wrong date")
                raise ReplyError(errors['WRONG_DATE'], job_status=SERVER_ERROR)
        
            else: # CONFIRM AND PENDING REPLY
                pass

        if decision == CANCEL:
            self.dates_to_update = [date for date in self.dates_to_update if date >= get_latest_date_past_8am()]

    def validate_confirmation_again(self, decision):
        '''This function will return if no errors are thrown, only accepts Cancel after OK'''
        if decision == CANCEL:
            from models.messages.received import MessageConfirm
            latest_confirm_msg = MessageConfirm.get_latest_confirm_message(self.job_no)
            if self.current_msg.ref_msg_sid != latest_confirm_msg.sid:
                raise ReplyError(errors['NOT_LAST_MSG'], job_status=None)
            # TODO future work... set job_status to none since other msges can still be replied to
            if self.local_db_updated:
                self.commit_cancel()
                return
            else:
                raise ReplyError(errors['JOB_MC_FAILED'])
    
        elif decision == CONFIRM and self.status == SERVER_ERROR:
            raise ReplyError(errors['CONFIRMING_CANCELLED_MSG'])
        else: # CONFIRM and unknown status
            raise ReplyError(errors['UNKNOWN_ERROR'])

    def run_background_tasks(self):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self.check_message_forwarded, (self.forwards_seq_no)),
                executor.submit(self.update_azure)
            ]
            # for future in as_completed(futures):
            #     try:
            #         result = future.result()
            #     except Exception as e:
            #         print(f'Task generated an exception: {e}')

            wait(futures)
        session = get_session()
        session.flush([self])
        session.refresh(self)
        self.check_for_complete()


    @overrides
    def handle_user_reply_action(self):
        updated_db_msg = self.update_local_db()
        self.forwards_seq_no = self.forward_messages()
        return f"{updated_db_msg}, messages have been forwarded. Pending success..."
    
    def update_local_db(self):
        if not self.is_cancelled:
            return McRecord.insert_local_db(self)
        else:
            return McRecord.delete_local_db(self)

    @overrides
    def entry_action(self):
        statuses = self.generate_base()
        reply = self.generate_msg_from_status(statuses)
        self.is_expecting_user_reply = True
        return reply

    @overrides
    def validate_complete(self):
        session = get_session()

        logging.info(f"session id in validate complete: {id(session)}")
        
        for instance in session.identity_map.values():
            logging.info(f"Instance in validate_complete session: {instance}")
        logging.info(type(self))
        

        self.logger.info(f"user: {self.user.name}, messages: {self.messages}")
        
        if self.local_db_updated:
            last_message_replied = self.all_messages_successful() # IMPT check for any double decisions before unblocking
            if last_message_replied:
                self.logger.info("all messages successful")
                return True
        self.logger.info("all messages successful")
        return False
    
    ########
    # ENTRY
    ########

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
            
                try:
                    overlap_status = self.validate_overlap()
                except AzureSyncError as e:
                    self.logger.info(e.message)
                    body = f"Hi {self.user.name}, we were unable to retrieve the current MC records. Please try again. If the problem persists, please check with the ICT department"
                    raise ReplyError(body)

                self.logger.info(f"Dates validated")
                
                return start_date_status, overlap_status
                
        except DurationError as e:
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

        print(f'duration: {duration}')

        return duration

        
    def set_start_end_date(self, message):
        '''This function takes in a mc_message and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = dates.named_month_extraction(message)
        ddmm_start, ddmm_end = dates.named_ddmm_extraction(message)
        day_start, day_end = dates.named_day_extraction(message)
        
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
                session.commit()
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

        start_date, duration = self.start_date, self.duration # these are actually functions

        def daterange():
            for n in range(duration):
                yield start_date + timedelta(n)

        all_dates_set = set(daterange())
        duplicate_records = McRecord.get_duplicates(self)
        duplicate_dates_set = set([record.date for record in duplicate_records])

        non_duplicate_dates_set = all_dates_set - duplicate_dates_set

        self.duplicate_dates = sorted(list(duplicate_dates_set))
        self.dates_to_update = sorted(list(non_duplicate_dates_set))

        self.duration = len(self.dates_to_update)

        session.commit()

    def generate_msg_from_status(self, statuses):
        '''self always has a job that is an JobMc object'''

        start_date_status, overlap_status = statuses

        self.logger.info(f"STATUSES: {start_date_status}, {overlap_status}")

        if overlap_status == CHANGED and start_date_status == CHANGED:
            cv_func = get_cv.get_later_start_date_and_overlap_confirm_mc_cv
            content_sid = os.environ.get("MC_LATER_START_DATE_AND_OVERLAP_CONFIRMATION_CHECK_SID")
        elif overlap_status == CHANGED: # check that it is an mc message
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
            raise ReplyError(errors['NO_RELATIONS'])
        else:
            return content_sid, content_variables

    
    ###################################
    # HANDLE USER REPLY
    ###################################

    def forward_messages(self):

        from models.messages.sent import MessageForward
        
        if not self.is_cancelled:
            self.content_sid = os.environ.get("MC_NOTIFY_SID")

        else: 
            self.content_sid = os.environ.get("MC_NOTIFY_CANCEL_SID") # USER CANCELS
        
        cv_and_relations_list = MessageForward.get_cv_and_users_list(MessageForward.get_forward_mc_cv, self.user, self)

        self.logger.info(f"forwarding messages with this cv list: {cv_and_relations_list}")

        [new_seq_no, successful_relations] = MessageForward.forward_template_msges(cv_and_relations_list, self)

        return new_seq_no
            
    @run_new_context()
    def update_azure(self):
        session = get_session()
        logging.info(f"session id in update_azure: {id(session)}")

        logging.basicConfig(
            filename='/var/log/app.log',  # Log file path
            filemode='a',  # Append mode
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
            level=logging.INFO  # Log level
        )
        
        logging.info("in update azure")

        all_mc_dates = []
        del_dates = []

        # upload to azure
        try:
            mmyy_arr = loop_mc_files()

            # check every 
            for mmyy, dates_list in self.new_dates.items():
                self.logger.info(f"mmyy: {mmyy}")

                manager = SpreadsheetManager(mmyy, self.user)
                existing_dates = manager.get_unique_current_dates()
                # dont extend yet since cancel decision needs to slice the array

                if not self.is_cancelled: # cfm
                    manager.upload_data(dates_list, self.leave_type)
                    # The call to get the dates often happen too fast, so we manually add the dates
                    all_mc_dates.extend(dates_list)
                else: # cancel
                    del_month_mc_dates = manager.delete_data(dates_list)
                    del_dates.extend(del_month_mc_dates)
                    existing_dates = [date for date in existing_dates if date not in del_month_mc_dates]

                all_mc_dates.extend(existing_dates)
                
                if mmyy in mmyy_arr:
                    mmyy_arr.remove(mmyy)
                    self.logger.info(f"removing {mmyy} from the array")
            
            for mmyy in mmyy_arr:
                manager = SpreadsheetManager(mmyy, self.user)
                current_mc_dates = manager.get_unique_current_dates()
                logging.info(f"Existing dates: {existing_dates}")
                existing_dates = current_mc_dates if len(current_mc_dates) > 0 else []
                all_mc_dates.extend(existing_dates)
                
            self.azure_status = OK

            if not self.is_cancelled:
                body = f"MC records have been updated on Sharepoint. You are on MC on {print_all_dates(all_mc_dates, date_obj=True)}"
            else:
                body = f"Hi {self.user.name}, "
                if len(del_dates) > 0:
                    body += f"Your future MC records have been deleted on Sharepoint for {print_all_dates(del_dates, date_obj=True)}. "
                if len(self.current_dates) > 0:
                    body += f"You are on MC on {print_all_dates(all_mc_dates, date_obj=True)}."
                else:
                    body += f"There are no other MC records under your name."

            MessageSent.send_msg(messages['SENT'], body, self)

        except AzureSyncError as e:
            self.logger.info(e.message)
            body = f"MC records FAILED to update. Please try again. If the problem persists, please check with the ICT department"
            raise ReplyError(body)
            

    