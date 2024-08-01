import os
from datetime import datetime

from models.exceptions import ReplyError, NoRelationsError

from models.jobs.base.constants import ErrorMessage, OutgoingMessageData, MessageType
from models.jobs.base.utilities import print_all_dates, get_latest_date_past_hour, clear_user_processing_state

from models.jobs.leave.Task import TaskLeave
from models.jobs.leave.constants import LeaveErrorMessage, LeaveError, LeaveType, LeaveStatus, LeaveTaskType
from models.jobs.leave.utilities import get_approve_leave_cv, get_authorisation_cv, get_authorisation_late_cv
from models.jobs.leave.LeaveRecord import LeaveRecord

from models.messages.MessageKnown import MessageKnown


class RequestAuthorisation(TaskLeave):

    __mapper_args__ = {
        "polymorphic_identity": LeaveTaskType.REQUEST_AUTHORISATION
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

    def handle_dates(self):

        if self.job.leave_type == LeaveType.MEDICAL or self.user.is_global_admin:
            self.dates_to_approve = set(self.dates_to_update)
            self.dates_to_authorise = set()
        else:
            self.dates_to_approve = {date for date in self.dates_to_update if date < get_latest_date_past_hour(day_offset=3)} # approve dates within 3 days
            self.dates_to_authorise = set(self.dates_to_update) - self.dates_to_approve

        self.dates_to_approve = list(self.dates_to_approve)
        self.dates_to_authorise = list(self.dates_to_authorise)
    
    def execute(self): # LEAVE_TYPE_FOUND

        self.setup_other_users()
        self.handle_dates()
        
        self.relations_name_list = [r.alias for r in self.relations_set]
        self.other_relations_set = self.relations_set - self.ro_set # cannot be null

        self.reply_message = OutgoingMessageData(
            msg_type=MessageType.SENT, 
            user_id=self.user_id, 
            job_no=self.job_no
        )
        self.forward_metadata = None

        if len(self.dates_to_authorise) > 0: # this only works because in handle_dates(), if no RO + no dates to approve (ie all pending), it is safe to immediately add to database
            LeaveRecord.add_leaves(self.job_no, self.dates_to_authorise)
        
        if len(self.dates_to_approve) > 0:
            LeaveRecord.add_leaves(self.job_no, self.dates_to_approve, leave_status=LeaveStatus.APPROVED)
            
            if len(self.dates_to_authorise) == 0: 
                self.handle_approve_all() # ALL APPROVE
            else:
                self.handle_approve_partial() # PARTIAL APPROVE
        else:
            if len(self.dates_to_authorise) == 0: # NO DATES FOUND
                message = OutgoingMessageData(
                    body=ErrorMessage.DATES_NOT_FOUND,
                    job_no=self.job_no,
                    user_id=self.user_id
                )
                raise ReplyError(message, LeaveError.UNKNOWN)
            else: # ALL PENDING, NOT URGENT
                # authorisers_list = list(self.user.get_ro().union(self.user.get_dept_admins())) # TODO ALLOW THIS?
                # if len(authorisers_list) == 0:
                #     raise NoRelationsError("Unable to find staff for acknowledgement process.")
                
                cv_list = get_authorisation_cv( # LOOP RELATIONS
                    self.ro_set, 
                    alias=self.user.alias, 
                    leave_type=self.job.leave_type, 
                    dates=self.dates_to_authorise,
                    relation_aliases=self.relations_name_list,
                    mark_late=True
                )

                self.forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_AUTHORISATION_REQUEST_SID"), cv_list=cv_list, users_list=self.ro_set)

                self.reply_message.content_sid = os.getenv('AUTHORISATION_REPLY_ALL_PENDING_SID')
                self.reply_message.content_variables = {
                    '1': self.job_no,
                    '2': print_all_dates(self.dates_to_authorise),
                    '3': 'acknowledgement'
                }

        if self.forward_metadata:
            MessageKnown.forward_template_msges(
                job_no=self.job.job_no, 
                callback=self.forwards_callback,
                user_id_to_update=self.user_id,
                message_context=f"your leave / leave request with Ref. {self.job_no}",
                **self.forward_metadata,
            )

        MessageKnown.send_msg(message=self.reply_message)

        # SET USER TO COMPLETED
        clear_user_processing_state(self.user_id)

        return
    
    def handle_approve_all(self):
        
        cv_list = get_approve_leave_cv( # LOOP RELATIONS
            self.relations_set, 
            alias=self.user.alias, 
            leave_type=self.job.leave_type, 
            dates=self.dates_to_approve,
            mark_late=True
        )

        self.forward_metadata = MessageKnown.construct_forward_metadata(sid=os.getenv("LEAVE_NOTIFY_APPROVE_SID"), cv_list=cv_list, users_list=self.relations_set)

        self.reply_message.content_sid = os.getenv('AUTHORISATION_REPLY_ALL_APPROVED_SID') 

        self.reply_message.content_variables = {
            '1': self.job_no,
            '2': print_all_dates(self.dates_to_approve),
            '3': 'acknowledged'
        }

        if len(self.ro_set) == 0:
            self.reply_message.content_variables['3'] += '. Also: No RO found which can cause issues in future'

    def handle_approve_partial(self): # PARTIAL APPROVE
        self.reply_message.content_sid = os.getenv('AUTHORISATION_REPLY_PARTIAL_SID')
        self.reply_message.content_variables = {
            '1': self.job_no,
            '2': print_all_dates(self.dates_to_approve),
            '3': 'acknowledged to apply on Tigernix',
            '4': print_all_dates(self.dates_to_authorise)
        }

        authorisation_cv_list = authorisation_sid_list = []

        if len(self.ro_set) == 0:
            self.reply_message.content_variables['4'] += ' has been voided as RO is not found. Please contact HR/ICT, thank you!'

        else:
            self.reply_message.content_variables['4'] += ' is pending acknowledgement.'

            authorisation_cv_list = get_authorisation_late_cv(
                self.ro_set, 
                alias=self.user.alias, 
                leave_type=self.job.leave_type, 
                dates_approved=self.dates_to_approve,
                dates_to_authorise=self.dates_to_authorise,
                relation_aliases=self.relations_name_list,
                mark_late=True
            )
            authorisation_sid_list = [os.getenv("LEAVE_AUTHORISATION_REQUEST_LATE_SID")] * len(authorisation_cv_list)
            
        # OTHER RELATIONS CANNOT BE NULL, WILL HANDLE IN APPROVE AFTERWARDS
        notify_cv_list = get_approve_leave_cv( # LOOP RELATIONS
            self.other_relations_set, 
            alias=self.user.alias, 
            leave_type=self.job.leave_type, 
            dates=self.dates_to_approve,
            mark_late=True
        )
        notify_sid_list = [os.getenv("LEAVE_NOTIFY_APPROVE_SID")] * len(notify_cv_list)

        self.forward_metadata = MessageKnown.construct_forward_metadata(
            sid=[*authorisation_sid_list, *notify_sid_list], 
            cv_list=[*authorisation_cv_list, *notify_cv_list], 
            users_list=[*self.ro_set, *list(self.other_relations_set)]
        )

            