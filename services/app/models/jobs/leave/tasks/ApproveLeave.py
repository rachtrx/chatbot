import os

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state\

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
        reply_message = OutgoingMessageData( 
            msg_type=MessageType.SENT, 
            user=self.user.alias, 
            job_no=self.job_no, 
        )
        
        forward_metadata = self.approve(self.payload)
        
        reply_message.body = f"Leave on {print_all_dates(self.affected_dates)} has been approved for {self.job.user.alias}, relevant staff will be notified."
        MessageKnown.send_msg(message=reply_message)

        follow_up_message = OutgoingMessageData(
            msg_type=MessageType.FORWARD,
            user=self.job.user,
            job_no=self.job_no,
            content_sid=os.environ.get('LEAVE_FOLLOW_UP_APPROVED_SID'),
            content_variables={
                '1': self.job.user.alias,
                '2': self.user.alias,
                '3': print_all_dates(self.affected_dates),
                '4': self.job_no
            }
        )
        MessageKnown.send_msg(message=follow_up_message)

        MessageKnown.forward_template_msges(
            self.job.job_no,
            callback=self.forwards_callback,
            user_id_to_update=self.job.user.id,
            message_context="your leave",
            **forward_metadata
        )

        clear_user_processing_state(self.user_id)

        return


    def approve(self, records):
        users_list = self.job.user.get_relations(ignore_users=[self.user])
        alias = self.job.user.alias
        approver_alias = self.user.alias
        self.affected_dates = LeaveRecord.update_leaves(records, LeaveStatus.CANCELLED)
        
        cv_list = get_approve_leave_cv( # LOOP USERS
            users_list, 
            alias=alias,
            leave_type=self.job.leave_type,
            dates=self.affected_dates,
            approver_alias=approver_alias
        )

        return MessageKnown.construct_forward_metadata(os.environ.get("LEAVE_NOTIFY_APPROVE_SID"), cv_list, users_list)

