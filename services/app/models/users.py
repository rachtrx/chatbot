from __future__ import annotations
import os
import shortuuid

from extensions import db, Session
from MessageLogger import setup_logger

from models.jobs.base.utilities import join_with_commas_and

# from models.jobs.daemon.constants import AccessLevel # KEEP OLD IMPLEMENTATION FOR NOW
# from sqlalchemy.types import Enum as SQLEnum

class User(db.Model):

    logger = setup_logger('models.user')

    __tablename__ = "users"
    id = db.Column(db.String(32), primary_key=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    alias = db.Column(db.String(80), nullable=False)
    number = db.Column(db.Integer(), nullable=False)
    dept = db.Column(db.String(64), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Self-referential relationships
    reporting_officer_id = db.Column(db.String(80), db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reporting_officer = db.relationship('User', remote_side=[id], post_update=True,
                                     backref=db.backref('reportees'), foreign_keys=[reporting_officer_id])
    
    is_global_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_dept_admin = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def sg_number(self):
        if not getattr(self, '_sg_number', None):
            self.sg_number = 'whatsapp:+65' + str(self.number)
        return self._sg_number
    
    @sg_number.setter
    def sg_number(self, value):
        self._sg_number = value

    def __init__(self, name, alias, number, dept, is_global_admin, is_dept_admin, reporting_officer=None):
        self.id = shortuuid.ShortUUID().random(length=8)
        self.name = name
        self.alias = alias
        self.number = number
        self.dept = dept
        self.reporting_officer = reporting_officer
        self.is_global_admin = is_global_admin
        self.is_dept_admin = is_dept_admin

    @classmethod
    def get_user(cls, from_number):
        session = Session()
        user = session.query(cls).filter_by(number=from_number[-8:]).first()
        print(f"User: {user}")
        if user:
            return user
        else:
            return None
        
    def get_ro(self):
        self.logger.info(f"RO: {self.reporting_officer}")
        return {self.reporting_officer} if self.reporting_officer else set()

    @classmethod
    def get_dept_admins(cls, dept):
        session = Session()
        query = session.query(cls).filter(
            User.is_dept_admin == True,
            User.dept == dept
        )
        dept_admins = query.all()
        return set(dept_admins) if dept_admins else set()

    @classmethod
    def get_global_admins(cls):
        session = Session()
        query = session.query(cls).filter(cls.is_global_admin == True)
        global_admins = query.all()
        return set(global_admins) if global_admins else set()

    def get_relations(self, ignore_users: list[User] = []):
        # Using list unpacking to handle both list and empty list cases
        relations = list(self.get_ro() | self.get_dept_admins(self.dept) | self.get_global_admins())
        if os.environ.get('LIVE') == "1":
            ignore_ids = {self.id}
            ignore_ids.update(user.id for user in ignore_users)
            relations = [user for user in relations if user.id not in ignore_ids]
            # self.logger.info(f"Final relations: {relations}")
        return relations
    
    @staticmethod
    def loop_users(func):
        '''This wrapper wraps any method of the Job class. Call the method on any job and pass in the user.
        
        Returns a list of each relation function call result if there are relations, returns None if no relations.
        
        The function being decorated must have relation as the first param such that it can use the relation'''

        def wrapper(relations, *args, **kwargs):

            results = []

            for relation in relations:
                result = func(relation, *args, **kwargs)
                results.append(result) # original function has to be called on an instance method of job pr user

            return results
        return wrapper
    
    def print_relations_list(self):
        user_list = []
        for relation in self.get_relations():
            user_list.append(f"{relation.alias} ({relation.number})")

        return join_with_commas_and(user_list)