from extensions import db, get_session
from typing import List
import re
from dateutil.relativedelta import relativedelta
from .abstract import Message
from .sent import MessageSent
from constants import leave_alt_words, Decision, AuthorizedDecision, LeaveType, Intent, MessageType
import logging
from sqlalchemy.types import Enum as SQLEnum

from MessageLoggersetup_logger

class MessageReceived(Message):

    logger = setup_logger('models.message_received')

    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    reply_sid = db.Column(db.String(80), nullable=True)

    __tablename__ = "message_received"

    __mapper_args__ = {
        "polymorphic_identity": "message_received"
    }

    def __init__(self, job_no, sid, body, seq_no=None):
        super().__init__(job_no, sid, body, seq_no) # initialise message

    @staticmethod
    def check_for_intent(message):
        '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''
        
        logging.info(f"message: {message}")
                
        leave_alt_words_pattern = re.compile(leave_alt_words, re.IGNORECASE)
        if leave_alt_words_pattern.search(message):
            return Intent.TAKE_LEAVE
            
        return Intent.ES_SEARCH
    
    @staticmethod
    def get_message(request):
        if "ListTitle" in request.form:
            message = request.form.get('ListTitle')
        else:
            message = request.form.get("Body")
        logging.info(f"Received {message}")
        return message
    
    @staticmethod
    def get_sid(request):
        sid = request.form.get("MessageSid")
        return sid

    def commit_reply_sid(self, sid):
        session = get_session()
        self.reply_sid = sid
        session.commit()
        self.logger.info(f"reply committed with sid {self.reply_sid}")

        return True

class MessageSelection(MessageReceived):

    logger = setup_logger('models.message_confirm')

    __tablename__ = "message_confirm"
    sid = db.Column(db.ForeignKey("message_received.sid"), primary_key=True)

    #for comparison with the latest confirm message. sid is of the prev message, not the next reply
    ref_msg_sid = db.Column(db.String(80), nullable=False)
    selection = db.Column(SQLEnum(Decision, AuthorizedDecision, LeaveType), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": "message_confirm",
        'inherit_condition': sid == MessageReceived.sid
    }

    def __init__(self, job_no, message):
        super().__init__(job_no, message['sid'], message['body']) # initialise message
        self.ref_msg_sid = message['ref_msg_sid']
        self.selection = message['selection']
    
    def check_for_other_selection(self):
        
        # other_selection = CANCEL if self.selection == CONFIRM else CANCEL
        session = get_session()

        other_message = session.query(MessageSelection) \
                        .filter(
                            MessageSelection.ref_msg_sid == self.ref_msg_sid,
                            MessageSelection.sid != self.sid,
                            # MessageSelection.selection == other_selection
                        ).first()
        
        # TODO not sure why other_selection doesnt work
        
        return other_message