from datetime import datetime, timedelta, date
from extensions import db
# from sqlalchemy.orm import 
from sqlalchemy import Column, ForeignKey, Integer, String, desc
from typing import List
import uuid
import re
from dateutil.relativedelta import relativedelta
from twilio.rest import Client
import os
from logs.config import setup_logger
from constants import FAILED
from utilities import get_relations_name_and_no_list
import json

class User(db.Model):

    logger = setup_logger('models.user')

    __tablename__ = "users"
    name = db.Column(db.String(80), primary_key=True, nullable=False)
    number = db.Column(db.Integer(), unique=True, nullable=False)
    dept = db.Column(db.String(50), nullable=False)

    # Self-referential relationships
    reporting_officer_name = db.Column(String(80), ForeignKey('users.name', ondelete='SET NULL'), nullable=True)
    reporting_officer = db.relationship('User', remote_side=[name], post_update=True,
                                     backref=db.backref('subordinates'), foreign_keys=[reporting_officer_name])
    
    is_global_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_dept_admin = db.Column(db.Boolean, default=False, nullable=False)

    is_blocking = db.Column(db.Boolean, default=False, nullable=False)

    # hod_name = db.Column(String(80), ForeignKey('users.name', ondelete='SET NULL'), nullable=True)
    # hod = db.relationship('User', remote_side=[name], post_update=True,
    #                                  backref=db.backref('dept_members'), foreign_keys=[hod_name])
    

    # reporting_officer = Column('User', backref=db.backref('subordinates'), remote_side=[name], post_update=True, foreign_keys=[reporting_officer_name])
    
    # hod_name = Column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    # hod = db.relationship('User', backref=db.backref('dept_members'), remote_side=[name], post_update=True, foreign_keys=[hod_name])

    @property
    def sg_number(self):
        return 'whatsapp:+65' + str(self.number) 

    def __init__(self, name, number, dept, is_global_admin, is_dept_admin, reporting_officer=None):
        self.name = name
        self.number = number
        self.dept = dept
        self.reporting_officer = reporting_officer
        self.is_global_admin = is_global_admin
        self.is_dept_admin = is_dept_admin

    @classmethod
    def get_user(cls, from_number):

        user = cls.query.filter_by(number=from_number).first()
        if user:
            return user
        else:
            return None
        
    @classmethod
    def get_principal(cls):
        principal = cls.query.filter_by(dept="Principal").first()
        if principal:
            return principal.name, principal.sg_number
        else:
            return None
        
    def get_ro(self):
        return [self.reporting_officer] if self.reporting_officer else []

    def get_dept_admins(self):
        dept_admins = User.query.filter(
            User.is_dept_admin == True,
            User.dept == self.dept,
            User.name != self.name
        ).all()
        return dept_admins if dept_admins else []

    def get_global_admins(self):
        global_admins = User.query.filter(
            User.is_global_admin == True,
            User.name != self.name
        ).all()
        return global_admins if global_admins else []

    def get_relations(self):
        # Using list unpacking to handle both list and empty list cases
        return set(self.get_ro()) | set(self.get_dept_admins()) | set(self.get_global_admins())
    
    ######################################################
    # FOR SENDING SINGLE REPLY MSG ABT ALL THEIR RELATIONS
    ######################################################

    def get_cv_many_relations(self, cv_func, *func_args):
        '''This function gets a mc_details object and returns the content variables for the message'''

        relations_list = get_relations_name_and_no_list(self)

        # no relations
        if relations_list == None or len(relations_list) < 1:
            return None
        
        self.logger.info(f"relations list: {relations_list}")

        content_variables = (cv_func(relations_list, *func_args))

        content_variables_json = json.dumps(content_variables)

        self.logger.info(json.dumps(content_variables, indent=4))

        return content_variables_json
