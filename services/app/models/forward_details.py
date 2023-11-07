from datetime import datetime, timedelta, date
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, month_mapping, day_mapping, TEMP, days_arr, PENDING_CALLBACK, FAILED, SUCCESS
import re
from dateutil.relativedelta import relativedelta
from twilio.rest import Client
import os

from .message import Message

class ForwardDetails(Message):

    #TODO other statuses eg. wrong duration

    __tablename__ = "forward_details"
    id: Mapped[int] = mapped_column(db.ForeignKey("message.id"), primary_key=True)
    ref_id: Mapped[int] = mapped_column(db.String(), db.ForeignKey('message.id', ondelete="CASCADE"), nullable=False)
    to_name: Mapped[str] = mapped_column(db.String(80), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "forward_details",
        'inherit_condition': id == Message.id
    }

    def __init__(self, id, ref_id, to_name, name, body, intent=intents['TAKE_MC']):
        timestamp = datetime.now()
        super().__init__(id, name, body, intent, TEMP, timestamp) # initialise message
        self.ref_id = ref_id
        self.to_name = to_name
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_all_forwards(cls, ref_id):
        msges = cls.query.filter_by(
            ref_id = ref_id
        )
        return msges

    def notify_status(self, status, client):
        if status == FAILED:
            client.messages.create(
                from_=os.environ.get("TWILIO_NO"),
                to=f"whatsapp:+65{self.user.number}",
                body=f"Message to {self.to_name} was UNSUCCESSFUL"
            )
        elif status == SUCCESS:
            client.messages.create(
                from_=os.environ.get("TWILIO_NO"),
                to=f"whatsapp:+65{self.user.number}",
                body=f"Message to {self.to_name} was successful"
            )