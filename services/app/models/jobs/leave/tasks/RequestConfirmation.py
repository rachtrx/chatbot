import os
import json
from datetime import datetime

from models.exceptions import ReplyError

from models.jobs.base.constants import MessageType, OutgoingMessageData, UserState, Decision, ErrorMessage
from models.jobs.base.utilities import set_user_state, combine_with_key_increment

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveIssue, LeaveType, Patterns, LeaveTaskType, LeaveError
from models.jobs.leave.utilities import set_dates_str, print_overlap_dates

from models.messages.MessageKnown import MessageKnown

class RequestConfirmation(TaskLeave):

    ###########################
    # SENDING CONFIRMATION
    ###########################

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.REQUEST_CONFIRMATION
    }

    def restore_cache(self, data):

        if not data:
            message = OutgoingMessageData(
                body=ErrorMessage.TIMEOUT_MSG,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message, LeaveError.TIMEOUT)

        self.dates_to_update = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in data['dates'] if data.get('dates', None)]
        self.duplicate_dates = [datetime.strptime(date_str, "%d-%m-%Y").date() for date_str in data['duplicate_dates'] if data.get('duplicate_dates', None)]
        if data.get('validation_errors', None):
            self.validation_errors = set([getattr(LeaveIssue, error) for error in data['validation_errors']]) 
        else:
            self.validation_errors = set()

    def update_cache(self):
        return {
            # created by generate base
            "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
            "duplicate_dates": [date.strftime("%d-%m-%Y") for date in self.duplicate_dates],
            "validation_errors": [error.name for error in list(self.validation_errors)] # IMPT REQUIRED IF LEAVE TYPE NOT DETECTED FIRST TIME
            # returned by generate base
            # can be blank after genenrate base
        }

    def execute(self): # LEAVE_TYPE_FOUND
        print("Getting leave type")

        leave_type = None

        if isinstance(self.payload, LeaveType):
            self.logger.info(f"Reply Received: {self.payload}")
            leave_type = self.payload

        else:
            leave_match = Patterns.LEAVE_KEYWORDS.search(self.payload)

            if leave_match:
                matched_term = leave_match.group(0) if leave_match else None
                for potential_leave_type, phrases in Patterns.LEAVE_KEYWORDS_DICT.items():
                    if matched_term.lower() in [phrase.lower() for phrase in phrases]:
                        leave_type = potential_leave_type
                        break
  
        if not leave_type:
            # UNKNOWN ERROR... keyword found but couldnt lookup

            self.cache.set(self.update_cache())

            message = OutgoingMessageData(
                user_id=self.user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SELECT_LEAVE_TYPE_SID'),
                content_variables=None
            )
            raise ReplyError(message)

        self.job.leave_type = leave_type

        reply_message = OutgoingMessageData(
            user_id=self.user_id, 
            job_no=self.job_no,
        )

        relations = self.get_relations()

        reply_message.content_sid, reply_message.content_variables = self.get_leave_confirmation_sid_and_cv()

        MessageKnown.send_msg(message=reply_message)

        set_user_state(user_id=self.user_id, state=UserState.PENDING)

        return

    def get_leave_confirmation_sid_and_cv(self):

        errors = self.validation_errors

        base_cv = {
            1: self.user.alias,
            2: self.job.leave_type.name.lower(),
            3: set_dates_str(self.dates_to_update, mark_late=True), # TODO DONT NEED TO MARK LATE?
            4: str(len(self.dates_to_update)),
            5: self.user.print_relations_list(),
            6: Decision.CONFIRM.value,
            7: Decision.CANCEL.value
        }

        if errors == {LeaveIssue.OVERLAP, LeaveIssue.UPDATED, LeaveIssue.LATE}:
            issues = {
                2: print_overlap_dates(self.duplicate_dates),
                3: LeaveIssue.UPDATED.value,
                4: LeaveIssue.LATE.value
            }
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_3_ISSUES_SID")
        elif errors == {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} or errors == {LeaveIssue.OVERLAP, LeaveIssue.LATE}:
            issues = {
                2: print_overlap_dates(self.duplicate_dates),
                3: LeaveIssue.UPDATED.value if {LeaveIssue.OVERLAP, LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif errors == {LeaveIssue.UPDATED, LeaveIssue.LATE}:
            issues = {
                2: LeaveIssue.UPDATED.value,
                3: LeaveIssue.LATE.value
            }
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")
        elif errors == {LeaveIssue.OVERLAP} or errors == {LeaveIssue.UPDATED} or errors == {LeaveIssue.LATE}:
            issues = {
                2: print_overlap_dates(self.duplicate_dates) if errors == {LeaveIssue.OVERLAP} else LeaveIssue.UPDATED.value if errors == {LeaveIssue.UPDATED} else LeaveIssue.LATE.value,
            }
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_1_ISSUE_SID")
        elif errors == set():
            issues = {}
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_SID")
        else:
            self.logger.error(f"UNCAUGHT errors IN CV: {errors}")
            message = OutgoingMessageData(
                body=ErrorMessage.UNKNOWN_ERROR,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message)
        
        cv = combine_with_key_increment(base_cv, issues)

        return content_sid, cv