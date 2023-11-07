from datetime import datetime, timedelta, date
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import desc
from typing import List
import uuid
from constants import intents, month_mapping, day_mapping, TEMP, days_arr, PENDING_CALLBACK, FAILED
import re
from dateutil.relativedelta import relativedelta
from twilio.rest import Client
import os

class User(db.Model):

    __tablename__ = "user"
    name: Mapped[str] = mapped_column(db.String(80), primary_key=True, nullable=False)
    number: Mapped[int] = mapped_column(db.Integer(), unique=True, nullable=False)
    messages = db.relationship('Message', backref=db.backref('user'), post_update=True)

    email: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)

    # Self-referential relationships
    reporting_officer_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    reporting_officer = db.relationship('User', backref=db.backref('subordinates'), remote_side=[name], post_update=True, foreign_keys=[reporting_officer_name])
    
    hod_name: Mapped[str] = mapped_column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    hod = db.relationship('User', backref=db.backref('dept_members'), remote_side=[name], post_update=True, foreign_keys=[hod_name])

    def __init__(self, name, number, email, reporting_officer=None, hod=None):
        self.name = name
        self.number = number
        self.email = email
        self.reporting_officer = reporting_officer
        self.hod = hod

    @classmethod
    def get_user(cls, from_number):
        user = cls.query.filter_by(number=from_number).first()
        if user:
            return user
        else:
            return None
        
    def get_ro(self):
        return self.reporting_officer if self.reporting_officer else None
    
    def get_hod(self):
        return self.hod if self.hod else None
        
    def get_relations(self):
        return (self.get_ro(), self.get_hod())

