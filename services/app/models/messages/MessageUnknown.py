from extensions import db
from models.jobs.base.constants import MessageOrigin
from models.messages.Message import Message

class MessageUnknown(Message):

    __tablename__ = 'message_unknown'

    user_no = db.Column(db.String, nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": MessageOrigin.UNKNOWN,
    }

    def __init__(self, sid, user_no, body):
        super().__init__(sid, body)
        self.user_no = user_no