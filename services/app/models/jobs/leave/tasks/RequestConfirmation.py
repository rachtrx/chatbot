import os
import json
import time
from datetime import datetime

from models.exceptions import ReplyError

from models.jobs.base.constants import MessageType, OutgoingMessageData, UserState, Decision, ErrorMessage
from models.jobs.base.utilities import set_user_state, combine_with_key_increment

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveType, Patterns, LeaveTaskType, LeaveError
from models.jobs.leave.utilities import set_dates_str

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
        
        if 'validation_errors' in data:
            self.validation_errors = data['validation_errors']
            self.logger.info(f'Validation errors: {self.validation_errors}')
        else:
            self.validation_errors = []

    def update_cache(self):
        return {
            "dates": [date.strftime("%d-%m-%Y") for date in self.dates_to_update],
            # "validation_errors": self.validation_errors
        }

    def execute(self): # LEAVE_TYPE_FOUND
        print("Getting leave type")

        self.setup_other_users()

        self.job.leave_type = None

        if LeaveType.get_by_id(self.payload):
            self.logger.info(f"Reply Received: {self.payload}")
            self.job.leave_type = LeaveType.get_by_id(self.payload).attr_name

        else:
            leave_match = Patterns.LEAVE_KEYWORDS.search(self.payload)

            if leave_match:
                matched_term = leave_match.group(0) if leave_match else None
                for potential_leave_type in Patterns.ALL_LEAVE_TYPES:
                    if matched_term.lower() in [keyword.lower() for keyword in potential_leave_type.keywords]:
                        self.job.leave_type = potential_leave_type.attr_name
                        break

        if not self.job.leave_type:

            self.cache.set(self.update_cache())

            leave_selection_1 = OutgoingMessageData(
                user_id=self.user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SELECT_LEAVE_TYPE_1_SID'),
                content_variables=None
            )
            MessageKnown.send_msg(message=leave_selection_1)
            time.sleep(0.5)
            leave_selection_2 = OutgoingMessageData(
                user_id=self.user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SELECT_LEAVE_TYPE_2_SID'),
                content_variables=None
            )
            MessageKnown.send_msg(message=leave_selection_2)
            time.sleep(0.5)
            leave_selection_3 = OutgoingMessageData(
                user_id=self.user_id,
                job_no=self.job_no,
                content_sid=os.getenv('SELECT_LEAVE_TYPE_3_SID'),
                content_variables=None
            )
            MessageKnown.send_msg(message=leave_selection_3)

            time.sleep(0.5)

            message = OutgoingMessageData(
                user_id=self.user_id,
                job_no=self.job_no,
                body='Please select one of the above leave types.'
            )
            raise ReplyError(message)

        reply_message = OutgoingMessageData(
            user_id=self.user_id, 
            job_no=self.job_no,
        )

        reply_message.content_sid, reply_message.content_variables = self.get_leave_confirmation_sid_and_cv()

        MessageKnown.send_msg(message=reply_message)

        set_user_state(user_id=self.user_id, state=UserState.PENDING)

        return

    def get_leave_confirmation_sid_and_cv(self):

        errors = self.validation_errors

        base_cv = {
            1: self.job_no,
            2: self.user.alias,
            3: LeaveType.convert_attr_to_text(self.job.leave_type),
            4: set_dates_str(self.dates_to_update, mark_late=True), # TODO DONT NEED TO MARK LATE?
            5: str(len(self.dates_to_update)) + ' week',
            6: Decision.CONFIRM,
            7: Decision.CANCEL
        }

        issues = {}
        content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_SID")

        if len(errors) > 0:
            issues['3'] = errors[0]
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_1_ISSUE_SID")
        
        if len(errors) > 1:
            issues['4'] = errors[1]
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_2_ISSUES_SID")

        if len(errors) > 3:
            issues['5'] = errors[2]
            content_sid = os.getenv("LEAVE_CONFIRMATION_CHECK_3_ISSUES_SID")
        
        cv = combine_with_key_increment(base_cv, issues)

        return content_sid, cv