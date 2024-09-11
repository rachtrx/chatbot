import os
from datetime import datetime

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.constants import ErrorMessage, OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveErrorMessage, LeaveError, LeaveType, LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_confirm_leave_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown


class ConfirmLeave(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.CONFIRM
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

    def execute(self): # LEAVE_TYPE_FOUND

        if len(self.dates_to_update) == 0: # NO DATES FOUND
            message = OutgoingMessageData(
                body=ErrorMessage.DATES_NOT_FOUND,
                job_no=self.job_no,
                user_id=self.user_id
            )
            raise ReplyError(message, LeaveError.UNKNOWN)

        self.setup_other_users()

        LeaveRecord.add_leaves(self.job_no, self.dates_to_update, leave_status=LeaveStatus.CONFIRMED)

        # Reply to person on leave
        self.reply_message = OutgoingMessageData(
            msg_type=MessageType.SENT, 
            user_id=self.user_id, 
            job_no=self.job_no
        )
        self.reply_message.content_sid = os.getenv('LEAVE_FOLLOW_UP_CONFIRM_SID')
        self.reply_message.content_variables = {
            '1': self.job_no,
            '2': print_all_dates(self.dates_to_update),
        }

        # Forward Messages
        cv_list = get_confirm_leave_cv( # LOOP RELATIONS
            self.relations_set, 
            alias=self.user.alias, 
            leave_type=self.job.leave_type, 
            dates=self.dates_to_update,
            mark_late=True
        )
        self.forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_NOTIFY_CONFIRM_SID"), cv_list=cv_list, users_list=self.relations_set)
        MessageKnown.forward_template_msges(
            job_no=self.job.job_no,
            callback=self.forwards_callback,
            user_id_to_update=self.user_id,
            message_context=f"your leave with Ref. {self.job_no}",
            **self.forward_metadata,
        )

        MessageKnown.send_msg(message=self.reply_message)

        # SET USER TO COMPLETED
        clear_user_processing_state(self.user_id)
        return