import re
import numpy as np

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from extensions import Session

from models.exceptions import ReplyError

from models.jobs.base.constants import OutgoingMessageData
from models.jobs.base.utilities import current_sg_time, print_all_dates, join_with_commas_and

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveIssue, LeaveError, LeaveErrorMessage, LeaveTaskType, AM_HOUR
from models.jobs.leave.utilities import duration_extraction, calc_start_end_date, named_month_extraction, named_ddmm_extraction, named_day_extraction, weekday_count
from models.jobs.leave.LeaveRecord import LeaveRecord

class ExtractDates(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.EXTRACT_DATES
    }

    def execute(self):

        self.setup_other_users()
        
        self.payload = re.sub(r'\s+', ' ', self.payload).strip()
        self.extract_dates()
        self.logger.info(f"{self.start_date}, {self.end_date}")

        # GET VALIDATION ERRORS FOR DATES
        self.validation_errors = set()
        self.check_for_past_dates()
        self.check_for_overlap() # sets dates_to_update and duplicate_dates
        self.check_for_late()

        self.logger.info(f"ERRORS: {[err for err in self.validation_errors]}")

        return
    
    def update_cache(self):
        self.logger.info(f"Updating dates in cache after extraction: {self.dates_to_update}")
        return {
            # created by generate base
            "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
            # returned by generate base
            "validation_errors": list(self.validation_errors),
            # can be blank after genenrate base
        }

    def extract_dates(self):
        self.start_date = self.end_date = self.duration = None

        self.logger.info(f"User string in generate base: {self.payload}")

        # self.duration is extracted duration
        if duration_extraction(self.payload):
            self.duration = int(duration_extraction(self.payload))

        duration_c = self.set_start_end_date() # checks for conflicts and sets the dates

        self.logger.info("start get_dates")
        
        if duration_c:
            # if there are specified dates and no duration
            self.logger.info(f"{self.duration}, {duration_c}")
            if self.duration == None:
                self.duration = duration_c
            # if there are specified dates and duration is wrong
            elif self.duration and self.duration != duration_c:

                body = f'The duration from {datetime.strftime(self.start_date, "%d/%m/%Y")} to {datetime.strftime(self.end_date, "%d/%m/%Y")} ({duration_c}) days) do not match with {self.duration} days. Please send another msg with the form "on leave from dd/mm to dd/mm" to indicate the MC. Thank you!'

                message = OutgoingMessageData(
                    body=body, 
                    job_no=self.job_no,
                    user_id=self.user_id,
                )
                raise ReplyError(
                    message=message,
                    error=LeaveError.DURATION_MISMATCH
                )
            
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
                self.start_date, self.end_date = calc_start_end_date(self.duration) # sets self.start_date, self.end_date
            except Exception: # start, end dates and duration not specified
                message = OutgoingMessageData(
                    body=LeaveErrorMessage.DATES_NOT_FOUND, 
                    job_no=self.job_no,
                    user_id=self.user_id,
                )
                raise ReplyError(
                    message=message,
                    error=LeaveError.DATES_NOT_FOUND
                )
        
    def set_start_end_date(self):
        '''This function uses msg and returns True or False, at the same time setting start and end dates where possible and resolving possible conflicts. Checks if can do something about start date, end date and duration'''

        named_month_start, named_month_end = named_month_extraction(self.payload)
        ddmm_start, ddmm_end = named_ddmm_extraction(self.payload)
        day_start, day_end = named_day_extraction(self.payload)
        
        start_dates = [date for date in [named_month_start, ddmm_start, day_start] if date is not None]
        end_dates = [date for date in [named_month_end, ddmm_end, day_end] if date is not None]

        self.logger.info(f"{start_dates}, {end_dates}")

        if len(start_dates) > 1:

            body = f'Conflicting start dates {join_with_commas_and(datetime.strptime(date, "%d/%m/%Y") for date in start_dates)}. Please send another msg with the form "on leave from dd/mm to dd/mm" to indicate the MC. Thank you!'

            message = OutgoingMessageData(
                body=body, 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(
                message=message,
                error=LeaveError.DURATION_MISMATCH
            )
        if len(end_dates) > 1:
            
            body = f'Conflicting end dates {join_with_commas_and(datetime.strptime(date, "%d/%m/%Y") for date in end_dates)}. Please send another msg with the form "on leave from dd/mm to dd/mm" to indicate the MC. Thank you!'

            message = OutgoingMessageData(
                body=body, 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(
                message=message,
                error=LeaveError.DURATION_MISMATCH
            )
        
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

        self.logger.info(f'duration: {duration}')

        return duration
    
    ####################
    # SECTION VALIDATION
    ####################
        
    def check_for_past_dates(self):
        '''Checks if start date is valid, otherwise tries to set the start date and duration'''
        cur_sg_date = current_sg_time().date()

        self.logger.info(f"{self.start_date}, {self.end_date}")
        # if end date is earlier than today, immediately reject
        if self.end_date < cur_sg_date:
            self.logger.info("date is too early cannot be fixed")
            body = f"Hi {self.user.alias}, I am no longer able to add your leave if you take it before today, sorry about the inconvenience."
            message = OutgoingMessageData(
                body=body, 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(
                message=message,
                error=LeaveError.ALL_PREVIOUS_DATES
            )
        
        # the start date is before today, but end date is at least today
        if self.start_date < cur_sg_date:
            self.logger.info("date is too early but can be fixed")
            self.start_date = cur_sg_date
            self.duration = (self.end_date - self.start_date).days + 1
            self.logger.info(f"committed in validate_start_date in session {id(Session())}")
            self.validation_errors.add(LeaveIssue.UPDATED)

    def check_for_overlap(self):

        start_date, duration = self.start_date, self.duration # these are actually functions

        def daterange():
            for n in range(duration):
                yield start_date + timedelta(n)

        all_dates_set = {d for d in set(daterange()) if np.is_busday(d.strftime('%Y-%m-%d'))}
        if weekday_count(all_dates_set) == 0:
            body = f"Hi {self.user.alias}, the leave system currently doesn't accept leave requests for weekends."
            message = OutgoingMessageData(
                body=body, 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(
                message=message,
                error=LeaveError.DATES_NOT_FOUND
            )

        duplicate_records = LeaveRecord.get_duplicates(self)
        duplicate_dates_set = set([record.date for record in duplicate_records])
        self.logger.info(f"Duplicate dates set: {duplicate_dates_set}")

        non_duplicate_dates_set = all_dates_set - duplicate_dates_set

        duplicate_dates = sorted(list(duplicate_dates_set))
        self.dates_to_update = sorted(list(non_duplicate_dates_set))
        # self.logger.info(f"Type of date: {type(self.dates_to_update[0])}")

        self.duration = len(self.dates_to_update)

        if len(duplicate_dates) != 0 and len(self.dates_to_update) != 0:
            self.logger.info("duplicates but can be fixed")
            self.validation_errors.add(LeaveIssue.OVERLAP + print_all_dates(duplicate_dates))
        elif len(duplicate_dates) != 0:
            self.logger.info("duplicates cannot be fixed")
            message = OutgoingMessageData(
                body=LeaveErrorMessage.ALL_OVERLAPPING, 
                job_no=self.job_no,
                user_id=self.user_id,
            )
            raise ReplyError(
                message=message,
                error=LeaveError.ALL_OVERLAPPING
            )
        else:
            pass
    
    def check_for_late(self):
        # the start date is now at least today, but we need to inform the user if it is already past 9am
        # self.logger.info(f"Checking for late: {current_sg_time().date()}, {current_sg_time().hour}")
        if current_sg_time().date() in self.dates_to_update and current_sg_time().hour >= AM_HOUR:
            self.validation_errors.add(LeaveIssue.LATE)

if __name__ == "__main__":
    sentence = input("Input a sentence")
    sentence = re.sub(r'\s+', ' ', sentence).strip()

    extract_dates_instance = ExtractDates(job_no='1')
    extract_dates_instance.extract_dates()