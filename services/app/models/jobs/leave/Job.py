from extensions import db

from overrides import overrides
from sqlalchemy.types import Enum as SQLEnum

from models.users import User
from models.exceptions import ReplyError

from models.jobs.base.Job import Job
from models.jobs.base.constants import JobType, Status, ErrorMessage, Decision, AuthorizedDecision
from models.jobs.base.utilities import is_user_status_exists

from models.jobs.leave.constants import LeaveTaskType, LeaveError, LeaveErrorMessage, LeaveType, LeaveStatus

class JobLeave(Job):

    __tablename__ = 'job_leave'
    
    job_no = db.Column(db.ForeignKey("job.job_no"), primary_key=True, nullable=False)
    error = db.Column(SQLEnum(LeaveError), nullable=False)
    leave_type = db.Column(SQLEnum(LeaveType), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": JobType.LEAVE,
    }

    ###########################
    # SECTION PREPROCESS
    ###########################

    def get_enum(self, message):
        if message in Decision._value2member_map_:
            return Decision(message)
        elif message in LeaveType._value2member_map_:
            return LeaveType(message) # TODO
        elif message in AuthorizedDecision._value2member_map_:
            return AuthorizedDecision(message)
        else:
            return None  
        
    def preprocess_msg(self, state, msg):
        '''returns the intermediate state'''
        msg_method_map = { # STATES A JOB CAN BE IN WHEN ACCEPTING A MESSAGE
            LeaveTaskType.EXTRACT_DATES: self.get_leave_selection,
            LeaveTaskType.REQUEST_CONFIRMATION: self.get_decision,
            LeaveTaskType.REQUEST_AUTHORISATION: self.get_authorisation, # IN PLACE OF LEAVE_CONFIRMED
            LeaveTaskType.APPROVE: self.get_selection_after_approval,
            LeaveTaskType.REJECT: self.get_selection_after_rejection,
            LeaveTaskType.CANCELLED: self.get_selection_after_cancelled,
        }

        func = msg_method_map.get(state)
    
        if func:
            return func(msg)
        else:
            raise ReplyError(
                body=Error.UNKNOWN_ERROR,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )

    def execute(self, msg, user_id):

        if self.error:
            err_msg = self.get_error_message()
            raise ReplyError(
                body=err_msg,
                user_id=self.primary_user_id,
                job_no=self.job_no
            ) # no need to update the error

        last_task = self.get_current_state()

        if not last_task:
            task = LeaveTaskType.EXTRACT_DATES

        elif last_task.status == Status.FAILED:
            raise ReplyError(
                body=ErrorMessage.UNKNOWN_ERROR, 
                user_id=self.primary_user_id,
                job_no=self.job_no,
                error=LeaveError.UNKNOWN
            )
        
        else:
            msg = self.get_enum(msg)
            task = self.preprocess_msg(last_task, msg) # raise other replyerrors
            
        payload = msg 
        
        if task in [LeaveTaskType.APPROVE, LeaveTaskType.REJECT, LeaveTaskType.CANCEL]:

            status_map = {
                LeaveTaskType.CANCEL: [LeaveStatus.APPROVED, LeaveStatus.PENDING],
                LeaveTaskType.APPROVE: [LeaveStatus.PENDING],
                LeaveTaskType.REJECT: [LeaveStatus.APPROVED]
            }

            statuses = status_map.get(task)

            from models.jobs.leave.LeaveRecord import LeaveRecord
            payload = LeaveRecord.get_records(self.job_no, statuses=statuses)
        
            if not payload:
                error_map = {
                    LeaveTaskType.CANCEL: LeaveErrorMessage.NO_DATES_TO_CANCEL,
                    LeaveTaskType.APPROVE: LeaveErrorMessage.NO_DATES_TO_APPROVE,
                    LeaveTaskType.REJECT: LeaveErrorMessage.NO_DATES_TO_REJECT
                }
                raise ReplyError(
                    body=error_map[task],
                    user_id=self.primary_user_id,
                    job_no=self.job_no,
                )
            
        from models.jobs.leave.tasks import ExtractDates, RequestConfirmation, RequestAuthorisation, ApproveLeave, RejectLeave, CancelLeave
                
        tasks_map = {
            LeaveTaskType.EXTRACT_DATES: [ExtractDates, RequestConfirmation],
            LeaveTaskType.REQUEST_CONFIRMATION: [RequestConfirmation],
            LeaveTaskType.REQUEST_AUTHORISATION: [RequestAuthorisation],
            LeaveTaskType.APPROVE: [ApproveLeave],
            LeaveTaskType.REJECT: [RejectLeave],
            LeaveTaskType.CANCEL: [CancelLeave]
        }

        task = None

        task_classes = tasks_map.get(task)
        for task_class in task_classes:
            task = task_class(self.job_no, user_id, payload)
            task.run()

        if not is_user_status_exists(user_id): 
            return True
        
        return False
            

    ###########################
    # HANDLING SELECTIONS
    ###########################
        

    def get_leave_selection(self, selection): # MESSAGE WHILE LEAVE_TYPE_NOT_FOUND
        print("Getting leave selection")
        if not isinstance(selection, LeaveType):
            raise ReplyError(
                body=Error.UNKNOWN_ERROR,
                user_id=self.primary_user_id,
                job_no=self.job_no,
            )

        return LeaveTaskType.REQUEST_CONFIRMATION
    
    @staticmethod
    def get_decision(selection): # MESSAGE WHILE PENDING_DECISION
        print("Getting Decision")

        action_map = {
            Decision.CONFIRM: LeaveTaskType.REQUEST_AUTHORISATION,
            Decision.CANCEL: LeaveError.REGEX,
        }

        return action_map.get(selection)
    
    def get_authorisation(self, selection): # MESSAGE WHILE PENDING_AUTHORISATION
        print("Getting authorisation")

        if isinstance(selection, LeaveType):
            raise ReplyError(
                body=Error.PENDING_AUTHORISATION,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )

        action_map = {
            AuthorizedDecision.APPROVE: LeaveTaskType.APPROVE,
            AuthorizedDecision.REJECT: LeaveTaskType.REJECT,
            Decision.CANCEL: LeaveTaskType.CANCEL # TODO check for last confirm message? # TODO start cancel process while pending validation
        }

        return action_map.get(selection)
            
    def get_selection_after_cancelled(self, selection): # MESSAGE WHILE LEAVE_CANCELLED
        print("Handling selection after cancelled")

        if isinstance(selection, AuthorizedDecision):
            raise ReplyError(
                body=LeaveError.AUTHORISING_CANCELLED_MSG,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(
                body=LeaveError.LEAVE_CANCELLED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    def get_selection_after_approval(self, selection): # MESSAGE WHILE LEAVE_APPROVED
        print("Handling selection after approval")

        if isinstance(selection, LeaveType):
            raise ReplyError(
                body=LeaveError.LEAVE_APPROVED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )

        action_map = {
            AuthorizedDecision.REJECT: LeaveTaskType.REJECT,
            Decision.CANCEL: LeaveTaskType.CANCEL, # TODO check for last confirm message? # TODO start cancel process while pending validation
            AuthorizedDecision.APPROVE: LeaveError.LEAVE_APPROVED,
        }
    
        return action_map.get(selection)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    def get_selection_after_rejection(self, selection): # MESSAGE WHILE LEAVE_REJECTED
        print("Handling selection after rejection")

        if isinstance(selection, AuthorizedDecision) and selection == AuthorizedDecision.APPROVE:
            raise ReplyError(
                body=LeaveError.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
        
        elif isinstance(selection, Decision) and selection == Decision.CANCEL:
            raise ReplyError(
                body=LeaveError.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            )
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(
                body=LeaveError.LEAVE_REJECTED,
                user_id=self.primary_user_id,
                job_no=self.job_no
            ) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        
    def get_error_message(status):

        message_map = {
            LeaveError.REGEX: LeaveErrorMessage.CONFIRMING_CANCELLED_MSG,
        }

        return message_map.get(status, ErrorMessage.UNKNOWN_ERROR)