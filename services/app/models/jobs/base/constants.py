import os
from enum import Enum
from dataclasses import dataclass

MAX_UNBLOCK_WAIT = 30
JOBS_PREFIX = "jobs"
LOG_LEVEL = 'error' if os.environ.get('LIVE') == 1 else 'info'

##################################
# JOB STATUSES
##################################

class ErrorMessage:
    TWILIO_ERROR = "There was an issue with the Whatsapp API provider."
    USER_NOT_FOUND = "I'm sorry, your contact is not in our database. Please check with HR and try again in an hour."
    PENDING_DECISION = "Please reply to the previous message first, thank you!"
    DOUBLE_MESSAGE = "The previous job has not completed or there was an error completing it. If the problem persists, please try again in 2 minutes, thank you!"
    UNKNOWN_ERROR = "Something went wrong, please send the message again"
    NO_RECENT_MSG = "I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?",
    DATES_NOT_FOUND = "The chatbot is still in development, we regret that we could not determine your period of MC, could you specify the dates/duration again?"
    ES_REPLY_ERROR = "The chatbot is still in development, we regret that we could not determine your intent. If you need additional help, please reach out to our new helpline 87178103."
    AZURE_SYNC_ERROR = "I'm sorry, something went wrong with the code, please check with ICT."
    MESSAGE_STILL_PENDING = "Sorry, please try again in a few seconds, a message sent to you is still pending success confirmation."
    JOB_NOT_FOUND = "Sorry, it seems like there are no records of this job in the database."
    MC_WRONG_SYNTAX = "Sorry, the message should specify the type of leave. Possible values: medical leave, ml, childcare leave, child care leave, ccl, parentcare leave, parent care leave, pcl, hospitalization leave, hospitalisation leave, hl, compassionate leave, cl"
    TIMEOUT_MSG = "Sorry, it seems like the previous message timed out."
    UNABLE_TO_CANCEL = "Sorry, the job cannot be cancelled; please check with ICT."
    SENT_MESSAGE_MISSING = "Sorry, it seems like we could not find the relavant job"
    JOB_COMPLETED = "Sorry, the job has either completed or has failed."
    NOT_LAST_MSG = "Please only reply to the latest message!"
    PENDING_AUTHORISATION = "This job is currently pending authorisation."
    NO_SUCCESSFUL_MESSAGES = "All messages failed to send."
    NO_FORWARD_MESSAGE_FOUND = "We could not find any staff to forward the request."

class JobType(Enum):
    LEAVE = "LEAVE"
    DAEMON = "DAEMON"
    UNKNOWN = "UNKNOWN"
    ES_SEARCH = "SEARCH"

class UserState(Enum):
    PROCESSING = 'PROCESSING'
    PENDING = 'PENDING'
    BLOCKED = 'BLOCKED'

class Status(Enum):
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    PENDING = 'PENDING'

class ForwardStatus:
    def __init__(self):
        for status in Status:
            setattr(self, status.name, [])

class MessageOrigin(Enum):
    KNOWN = 'KNOWN'
    UNKNOWN = 'UNKNOWN'
    NONE = 'NONE'

class MessageType(Enum):
    SENT = 'SENT'
    RECEIVED = 'RECEIVED'
    FORWARD = 'FORWARD'
    NONE = 'NONE'

@dataclass
class OutgoingMessageData:
    from models.users import User
    msg_type: MessageType
    user: User
    job_no: str | None
    body: str | None
    content_sid: str | None
    content_variables: dict | None

class Decision(Enum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"

class AuthorizedDecision(Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"