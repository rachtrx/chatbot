from sqlalchemy.types import Enum as SQLEnum
from sqlalchemy.ext.declarative import declared_attr

from extensions import db
from MessageLogger import setup_logger

from models.jobs.base.constants import MessageOrigin, MessageType
from models.jobs.base.utilities import current_sg_time

class MessageBase(db.Model):

    __tablename__ = 'message_base'

    @declared_attr
    def logger(cls):
        return setup_logger(f'models.{cls.__name__.lower()}')

    sid = db.Column(db.String(80), primary_key=True, nullable=False)
    body = db.Column(db.String(), nullable=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    type = db.Column(SQLEnum(MessageOrigin), nullable=False)
    msg_type = db.Column(SQLEnum(MessageType), nullable=False)

    __mapper_args__ = {
        "polymorphic_identity": MessageOrigin.NONE,
        "polymorphic_on": type
    }
    
    def __init__(self, sid, body):
        self.sid = sid
        self.body = body
        self.timestamp = current_sg_time()