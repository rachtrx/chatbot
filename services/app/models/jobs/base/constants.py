from enum import Enum
from dataclasses import dataclass
import os

MAX_UNBLOCK_WAIT = 30
JOBS_PREFIX = "jobs"
MESSAGING_SERVICE_SID = os.getenv('MESSAGING_SERVICE_SID') if int(os.getenv('LIVE')) else os.getenv('MESSAGING_SERVICE_SID_DEV')
TWILIO_NO = os.getenv('TWILIO_NO') if int(os.getenv('LIVE')) else os.getenv('TWILIO_NO_DEV')

class Constants:
    @classmethod
    def values(cls):
        return {v for k, v in cls.__dict__.items() if not k.startswith('__') and not callable(v)}

##################################
# JOB STATUSES
##################################

class ErrorMessage:
    TWILIO_ERROR = "There was an issue with the Whatsapp API provider."
    TWILIO_EMPTY_VARIABLES = "There was an issue creating the message."
    USER_NOT_FOUND = "I'm sorry, your contact is not in our database. Please check with HR and try again in an hour."
    PENDING_DECISION = "Please reply to the previous message first, thank you!"
    DOUBLE_MESSAGE = "The previous job has not completed or there was an error completing it. If the problem persists, please try again in 2 minutes, thank you!"
    UNKNOWN_ERROR = "Something went wrong, please send the message again"
    NO_RECENT_MSG = "I'm sorry, we could not find any messages from you in the past 5 minutes, could you send it again?",
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
    NO_FORWARD_MESSAGE_FOUND = "We could not find any staff to forward the request. Please ignore if this is normal behaviour. Otherwise, you may have to inform relevant staff manually."
    NO_ADMINS_FOUND = "No admins found to run health check"

class JobType:
    NONE = "NONE"
    LEAVE = "LEAVE"
    DAEMON = "DAEMON"
    SEARCH = "SEARCH"

class UserState:
    PROCESSING = 'PROCESSING'
    PENDING = 'PENDING'
    BLOCKED = 'BLOCKED'

class StatusMeta(type):
    def __iter__(cls):
        return (attr for attr in cls.__dict__ if not attr.startswith('__') and not callable(getattr(cls, attr)))

class Status(metaclass=StatusMeta):
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    PENDING = 'PENDING'

class ForwardStatus:
    def __init__(self):
        for status in Status:
            status_value = getattr(Status, status)
            setattr(self, status_value, [])

class MessageOrigin:
    KNOWN = 'KNOWN'
    UNKNOWN = 'UNKNOWN'
    NONE = 'NONE'

class MessageType:
    SENT = 'SENT'
    RECEIVED = 'RECEIVED'
    FORWARD = 'FORWARD'
    NONE = 'NONE'

@dataclass
class OutgoingMessageData:
    user_id: str
    msg_type: MessageType = MessageType.SENT
    job_no: str | None = None
    body: str | None = None
    content_sid: str | None = None
    content_variables: dict | None = None

class Decision(Constants):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"

class AuthorizedDecision(Constants):
    APPROVE = "APPROVE"
    REJECT = "REJECT"