from __future__ import annotations
import os
import shortuuid
from sqlalchemy.schema import UniqueConstraint

from extensions import db, Session
from MessageLogger import setup_logger

from models.exceptions import NoRelationsError
from models.jobs.base.utilities import join_with_commas_and

class Lookup(db.Model):

    logger = setup_logger('models.user')

    __tablename__ = "lookups"
    id = db.Column(db.String(32), primary_key=True, nullable=False)
    user_id = db.Column(db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    lookup_id = db.Column(db.db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    is_reporting_officer = db.Column(db.Boolean, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id], backref='lookups', lazy='select')
    lookup_user = db.relationship('User', foreign_keys=[lookup_id], backref='reportees', lazy='select')

    __table_args__ = (UniqueConstraint('user_id', 'lookup_id', name='_user_lookup_uc'),)

    def __init__(self, user_id, lookup_id, is_reporting_officer):
        self.id = shortuuid.ShortUUID().random(length=8).upper()
        self.user_id = user_id
        self.lookup_id = lookup_id
        self.is_reporting_officer = is_reporting_officer

    