from extensions import db
from models.jobs.base.constants import MessageOrigin
from models.messages.Message import Message

class MessageUnknown(Message):

    __tablename__ = 'message_unknown'

    sid = db.Column(db.String(64), db.ForeignKey('message.sid'), primary_key=True, nullable=False)
    user_no = db.Column(db.String(16), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": MessageOrigin.UNKNOWN,
    }

    def __init__(self, sid, user_no, body):
        super().__init__(sid, body)
        idx = user_no.find('+')
        if idx != -1:
            user_no = user_no[idx:]
        self.user_no = user_no