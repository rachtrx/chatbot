from extensions import db

from overrides import overrides
from sqlalchemy.types import Enum as SQLEnum

from models.users import User
from models.exceptions import ReplyError, DurationError

from models.jobs.base.Job import BaseJob
from models.jobs.base.constants import JobType, Status, ErrorMessage, LeaveError, Error, LeaveType, Decision, LeaveStatus, AuthorizedDecision
from models.jobs.base.utilities import is_user_status_exists

from models.jobs.leave.tasks import ExtractDates, RequestConfirmation, RequestAuthorisation, ApproveLeave, RejectLeave, CancelLeave, SendError
from models.jobs.leave.constants import TaskType, LeaveError, LeaveErrorMessage
from models.jobs.leave.LeaveRecord import LeaveRecord

class JobLeave(BaseJob):
    
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
            TaskType.EXTRACT_DATES: self.get_leave_selection,
            TaskType.REQUEST_CONFIRMATION: self.get_decision,
            TaskType.REQUEST_AUTHORISATION: self.get_authorisation, # IN PLACE OF LEAVE_CONFIRMED
            TaskType.APPROVE: self.get_selection_after_approval,
            TaskType.REJECT: self.get_selection_after_rejection,
            TaskType.CANCELLED: self.get_selection_after_cancelled,
        }

        func = msg_method_map.get(state)
    
        if func:
            return func(msg)
        else:
            raise ReplyError(Error.UNKNOWN_ERROR)

    def execute(self, msg, user_id):

        if self.error:
            err_msg = self.get_error_message()
            raise ReplyError(err_msg) # no need to update the error

        last_task = self.get_current_state()

        if not last_task:
            task = TaskType.EXTRACT_DATES

        elif last_task.status == Status.FAILED:
            raise ReplyError(ErrorMessage.UNKNOWN_ERROR, LeaveError.UNKNOWN)
        
        else:
            msg = self.get_enum(msg)
            task = self.preprocess_msg(last_task, msg) # raise other replyerrors
            
        payload = msg 
        
        if task in [TaskType.APPROVE, TaskType.REJECT, TaskType.CANCEL]:

            status_map = {
                TaskType.CANCEL: [LeaveStatus.APPROVED, LeaveStatus.PENDING],
                TaskType.APPROVE: [LeaveStatus.PENDING],
                TaskType.REJECT: [LeaveStatus.APPROVED]
            }

            statuses = status_map.get(task)
            payload = LeaveRecord.get_records(self.job_no, statuses=statuses)
        
            if not payload:
                error_map = {
                    TaskType.CANCEL: LeaveErrorMessage.NO_DATES_TO_CANCEL,
                    TaskType.APPROVE: LeaveErrorMessage.NO_DATES_TO_APPROVE,
                    TaskType.REJECT: LeaveErrorMessage.NO_DATES_TO_REJECT
                }
                raise ReplyError(error_map[task])
                
        tasks_map = {
            TaskType.EXTRACT_DATES: [ExtractDates, RequestConfirmation],
            TaskType.REQUEST_CONFIRMATION: [RequestConfirmation],
            TaskType.REQUEST_AUTHORISATION: [RequestAuthorisation],
            TaskType.APPROVE: [ApproveLeave],
            TaskType.REJECT: [RejectLeave],
            TaskType.CANCEL: [CancelLeave]
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
            raise ReplyError(Error.UNKNOWN_ERROR)

        return TaskType.REQUEST_CONFIRMATION
    
    @staticmethod
    def get_decision(selection): # MESSAGE WHILE PENDING_DECISION
        print("Getting Decision")

        action_map = {
            Decision.CONFIRM: TaskType.REQUEST_AUTHORISATION,
            Decision.CANCEL: LeaveError.REGEX,
        }

        return action_map.get(selection)
    
    @staticmethod
    def get_authorisation(selection): # MESSAGE WHILE PENDING_AUTHORISATION
        print("Getting authorisation")

        if isinstance(selection, LeaveType):
            raise ReplyError(Error.PENDING_AUTHORISATION)

        action_map = {
            AuthorizedDecision.APPROVE: TaskType.APPROVE,
            AuthorizedDecision.REJECT: TaskType.REJECT,
            Decision.CANCEL: TaskType.CANCEL # TODO check for last confirm message? # TODO start cancel process while pending validation
        }

        return action_map.get(selection)
            
    @staticmethod
    def get_selection_after_cancelled(selection): # MESSAGE WHILE LEAVE_CANCELLED
        print("Handling selection after cancelled")

        if isinstance(selection, AuthorizedDecision):
            raise ReplyError(LeaveError.AUTHORISING_CANCELLED_MSG)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_CANCELLED)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    @staticmethod
    def get_selection_after_approval(selection): # MESSAGE WHILE LEAVE_APPROVED
        print("Handling selection after approval")

        if isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_APPROVED)

        action_map = {
            AuthorizedDecision.REJECT: TaskType.REJECT,
            Decision.CANCEL: TaskType.CANCEL, # TODO check for last confirm message? # TODO start cancel process while pending validation
            AuthorizedDecision.APPROVE: LeaveError.LEAVE_APPROVED,
        }
    
        return action_map.get(selection)
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
    
    @staticmethod
    def get_selection_after_rejection(selection): # MESSAGE WHILE LEAVE_REJECTED
        print("Handling selection after rejection")

        if isinstance(selection, AuthorizedDecision) and selection == AuthorizedDecision.APPROVE:
            raise ReplyError(LeaveError.LEAVE_REJECTED)
        
        elif isinstance(selection, Decision) and selection == Decision.CANCEL:
            raise ReplyError(LeaveError.LEAVE_REJECTED)
    
        elif isinstance(selection, LeaveType):
            raise ReplyError(LeaveError.LEAVE_REJECTED) # TODO job_status is now only for leave class?
        
        # TODO possible for Decision to be here? ie. if there are more than 1 Decision messages
        
    def get_error_message(status):

        message_map = {
            LeaveError.REGEX: LeaveErrorMessage.CONFIRMING_CANCELLED_MSG,
        }

        return message_map.get(status, ErrorMessage.UNKNOWN_ERROR)