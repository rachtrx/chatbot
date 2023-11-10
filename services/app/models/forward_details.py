from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
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
    sid = db.Column(db.ForeignKey("message.sid"), primary_key=True)
    ref_sid = db.Column(db.String(50), db.ForeignKey('message.sid', ondelete="CASCADE"), nullable=False)
    to_name = db.Column(db.String(80), nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "forward_details",
        'inherit_condition': sid == Message.sid
    }

    def __init__(self, sid, ref_sid, to_name, name, body, intent=intents['TAKE_MC']):
        timestamp = datetime.now()
        super().__init__(sid, name, body, intent, TEMP, timestamp) # initialise message
        self.ref_sid = ref_sid
        self.to_name = to_name
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_all_forwards(cls, ref_sid):
        msges = cls.query.filter_by(
            ref_sid = ref_sid
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