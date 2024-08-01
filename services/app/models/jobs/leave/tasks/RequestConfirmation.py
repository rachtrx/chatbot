import os
import json
from datetime import datetime

from models.exceptions import ReplyError

from models.jobs.base.constants import MessageType, OutgoingMessageData, UserState, Decision, ErrorMessage
from models.jobs.base.utilities import set_user_state, combine_with_key_increment, get_latest_date_past_hour

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
        self.handle_dates()

        leave_type = None

        if self.payload in LeaveType.values():
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

        reply_message.content_sid, reply_message.content_variables = self.get_leave_confirmation_sid_and_cv()

        MessageKnown.send_msg(message=reply_message)

        set_user_state(user_id=self.user_id, state=UserState.PENDING)

        return

    def get_leave_confirmation_sid_and_cv(self):

        errors = self.validation_errors

        base_cv = {
            1: self.job_no,
            2: self.user.alias,
            3: self.job.leave_type.lower(),
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