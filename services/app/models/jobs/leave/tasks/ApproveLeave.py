import os

from models.exceptions import NoRelationsError

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.LeaveRecord import LeaveRecord
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_approve_leave_cv

from models.messages.MessageKnown import MessageKnown

class ApproveLeave(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.APPROVE
    }

    def execute(self):

        self.affected_dates = LeaveRecord.update_leaves(self.payload, LeaveStatus.APPROVED)
        reply_body = f"Leave on {print_all_dates(self.affected_dates)} has been approved, notifying {self.job.primary_user.alias}"

        forward_metadata = None
        try:
            forward_metadata = self.get_approval_forward_cv()
            others_body = ". Other staff will be notified."
        except NoRelationsError:
            others_body = ". No other staff were found to notify."
            
        follow_up_message = OutgoingMessageData(
            msg_type=MessageType.FORWARD,
            user_id=self.job.primary_user_id,
            job_no=self.job_no,
            content_sid=os.getenv('LEAVE_FOLLOW_UP_APPROVED_SID'),
            content_variables={
                '1': self.job_no,
                '2': self.job.primary_user.alias,
                '3': self.user.alias,
                '4': 'acknowledged',
                '5': print_all_dates(self.affected_dates) + others_body, # TODO ADD REPLY BODY??
            }
        )

        MessageKnown.send_msg(message=follow_up_message)

        if forward_metadata:
            MessageKnown.forward_template_msges(
                self.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.primary_user.id,
                message_context="your leave",
                **forward_metadata
            )

        reply_message = OutgoingMessageData( 
            user_id=self.user.id, 
            job_no=self.job_no, 
            body=reply_body + others_body
        )

        MessageKnown.send_msg(message=reply_message)

        clear_user_processing_state(self.user_id)
        return

    def get_approval_forward_cv(self):

        users_list = self.job.primary_user.get_relations(ignore_users=[self.user])
        alias = self.job.primary_user.alias
        approver_alias = self.user.alias
        
        cv_list = get_approve_leave_cv( # LOOP USERS
            users_list, 
            alias=alias,
            leave_type=self.job.leave_type,
            dates=self.affected_dates,
            approver_alias=approver_alias
        )

        return MessageKnown.construct_forward_metadata(os.getenv("LEAVE_NOTIFY_APPROVE_SID"), cv_list, users_list)

