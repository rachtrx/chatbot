import os

from models.jobs.base.constants import OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, clear_user_processing_state

from models.jobs.leave.Task import LeaveTask
from models.jobs.leave.constants import LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_reject_leave_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown

class RejectLeave(LeaveTask):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.REJECT
    }

    def execute(self):

        forward_metadata = self.reject(self.payload)

        reply_message = OutgoingMessageData( 
            msg_type=MessageType.SENT, 
            user=self.user.alias, 
            job_no=self.job_no, 
            body=f"Leave on {print_all_dates(self.affected_dates)} has been rejected for {self.job.user.alias}, relevant staff have been notified."
        )
        MessageKnown.send_msg(message=reply_message)

        follow_up_message = OutgoingMessageData(
            msg_type=MessageType.FORWARD,
            user=self.job.user,
            job_no=self.job_no,
            content_sid=os.environ.get('LEAVE_FOLLOW_UP_REJECTED_SID'),
            content_variables={
                '1': self.job.user.alias,
                '2': self.user.alias,
                '3': print_all_dates(self.affected_dates),
                '4': self.job_no
            }
        )
        MessageKnown.send_msg(message=follow_up_message)

        if forward_metadata: # REJECT WITH NO APPROVAL DOES NOT FORWARD
            MessageKnown.forward_template_msges(
                self.job.job_no,
                callback=self.forwards_callback,
                user_id_to_update=self.job.user.id,
                message_context="your leave rejection",
                **forward_metadata
            )

        clear_user_processing_state(self.user_id)

        return

    def reject(self, records):
        self.affected_dates = [record.date for record in records]

        # FORWARD MESSAGES
        users_list = None
        if any(record.status == LeaveStatus.APPROVED for record in records):
            users_list = self.job.user.get_relations(ignore_users=[self.user])

        self.affected_dates = LeaveRecord.update_leaves(records, LeaveStatus.REJECTED)

        if users_list: # SEND ONLY IF PREVIOUSLY APPROVED
            alias = self.job.user.alias
            approver_alias = self.user.alias
            
            cv_list = get_reject_leave_cv( # LOOP USERS
                users_list, 
                approver_alias=approver_alias,
                dates=self.affected_dates,
                alias=alias,
            )
        
            return MessageKnown.construct_forward_metadata(os.environ.get("LEAVE_NOTIFY_REJECT_SID"), cv_list, users_list)
