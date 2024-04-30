from extensions import db, get_session
# from sqlalchemy.orm import 
from sqlalchemy import ForeignKey
from logs.config import setup_logger
from constants import MAX_UNBLOCK_WAIT
import os

class User(db.Model):

    logger = setup_logger('models.user')

    __tablename__ = "users"
    name = db.Column(db.String(80), primary_key=True, nullable=False)
    alias = db.Column(db.String(80), nullable=False)
    number = db.Column(db.Integer(), unique=True, nullable=False)
    dept = db.Column(db.String(50), nullable=True)

    # Self-referential relationships
    reporting_officer_name = db.Column(db.String(80), ForeignKey('users.name', ondelete='SET NULL'), nullable=True)
    reporting_officer = db.relationship('User', remote_side=[name], post_update=True,
                                     backref=db.backref('subordinates'), foreign_keys=[reporting_officer_name])
    
    is_global_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_dept_admin = db.Column(db.Boolean, default=False, nullable=False)

    # hod_name = db.Column(String(80), ForeignKey('users.name', ondelete='SET NULL'), nullable=True)
    # hod = db.relationship('User', remote_side=[name], post_update=True,
    #                                  backref=db.backref('dept_members'), foreign_keys=[hod_name])
    

    # reporting_officer = Column('User', backref=db.backref('subordinates'), remote_side=[name], post_update=True, foreign_keys=[reporting_officer_name])
    
    # hod_name = Column(db.String(80), db.ForeignKey('user.name', ondelete="SET NULL"), nullable=True)
    # hod = db.relationship('User', backref=db.backref('dept_members'), remote_side=[name], post_update=True, foreign_keys=[hod_name])


    @property
    def sg_number(self):
        if not getattr(self, '_sg_number', None):
            self.sg_number = 'whatsapp:+65' + str(self.number)
        return self._sg_number
    
    @sg_number.setter
    def sg_number(self, value):
        self._sg_number = value

    def __init__(self, name, alias, number, dept, is_global_admin, is_dept_admin, reporting_officer=None):
        self.name = name
        self.alias = alias
        self.number = number
        self.dept = dept
        self.reporting_officer = reporting_officer
        self.is_global_admin = is_global_admin
        self.is_dept_admin = is_dept_admin

    @classmethod
    def get_user(cls, from_number):
        session = get_session()
        user = session.query(cls).filter_by(number=from_number[-8:]).first()
        print(f"User: {user}")
        if user:
            return user
        else:
            return None
        
    @classmethod
    def get_principal(cls):

        session = get_session()

        principal = session.query(cls).filter_by(dept="Principal").first()
        if principal:
            return principal.name, principal.sg_number
        else:
            return None
        
    def get_ro(self):
        self.logger.info(f"RO: {self.reporting_officer}")
        return [self.reporting_officer] if self.reporting_officer else []

    @classmethod
    def get_dept_admins(cls, dept):
        session = get_session()
        query = session.query(cls).filter(
            User.is_dept_admin == True,
            User.dept == dept
        )
        dept_admins = query.all()
        return dept_admins if dept_admins else []

    @classmethod
    def get_global_admins(cls):
        session = get_session()
        query = session.query(cls).filter(cls.is_global_admin == True)
        global_admins = query.all()
        return global_admins if global_admins else []

    def get_relations(self):
        # Using list unpacking to handle both list and empty list cases
        relations = list(set(self.get_ro()) | set(self.get_dept_admins(self.dept)) | set(self.get_global_admins()))
        if os.environ.get('LIVE') == "1":
            relations = [user for user in relations if user.name != self.name]
        # self.logger.info(f"Final relations: {relations}")
        return relations