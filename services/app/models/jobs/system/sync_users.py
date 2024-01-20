from models.jobs.system.abstract import JobSystem
from overrides import overrides
import os
from sqlalchemy.exc import IntegrityError

import requests
import pandas as pd
import numpy as np
import traceback
from datetime import datetime
import json

from azure.utils import generate_header
from extensions import db
from models.users import User

from utilities import current_sg_time
from logs.config import setup_logger
from constants import OK, FAILED
from utilities import current_sg_time, join_with_commas_and

class JobSyncUsers(JobSystem): # probably sync mc eventually too

    logger = setup_logger('models.job_sync_users')

    __tablename__ = 'job_sync_users'

    job_no = db.Column(db.ForeignKey("job_system.job_no"), primary_key=True)
    
    __mapper_args__ = {
        "polymorphic_identity": "job_sync_users",
    }

    def __init__(self):
        super().__init__() # admin name is default
        self.header = generate_header()
        self.failed_users = []
        self.affected_users = []

    def sync_user_info(self):

        '''Returns a 2D list containing the user details within the inner array'''

        USERS_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/MainTable/tables/MainTable/rows"

        # print(manager.headers)

        # Make a GET request to the provided url, passing the access token in a header

        response = requests.get(url=USERS_TABLE_URL, headers=self.header)
        data = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]

        # print(lookups_arrs)

        # print(f"user info: {user_arrs}")

        return data # info is already a list so user_info is a 2D list


    @staticmethod
    def df_replace_spaces(df):
        '''removes the blank rows in the dataframe'''
        df.replace('', np.nan, inplace=True)
        df = df.dropna(how="all", inplace=True)
        return df

    def update_user_database(self):

        col_order = ['name', 'number', 'dept', 'reporting_officer_name', 'is_global_admin', 'is_dept_admin']

        # SECTION AZURE SIDE
        data = self.sync_user_info()

        az_users = pd.DataFrame(data=data, columns=["name", "number", "dept", "reporting_officer_name", "access"])
        self.df_replace_spaces(az_users)
        # print(users)
        try:
            az_users['number'] = az_users["number"].astype(int)
        except:
            nan_mask = az_users["number"].isna()
            nan_names = az_users.loc[nan_mask, 'name']
            names_arr = nan_names.values
            body = f"The phone number is missing for {', '.join(names_arr)}"
            # MessageSent.send_msg(body)
            # Message.create_message(messages['SENT'], sent_message_meta.sid, body) #TODO make a job?

        az_users['is_global_admin'] = (az_users['access'] == 'GLOBAL')
        az_users['is_dept_admin'] = (az_users['access'] == 'DEPT')
        az_users.drop(columns=["access"])
        az_users.sort_values(by="name", inplace=True)
        az_users = az_users[col_order]

        # SECTION DB SIDE, need app context
        db_users = User.query.order_by(User.name).all()  # ORM way to fetch users
        db_users_list = [[user.name, user.number, user.dept, user.reporting_officer_name, user.is_global_admin, user.is_dept_admin, user.is_blocking] for user in db_users]
        column_names = [column.name for column in User.__table__.columns]
        print(column_names, db_users_list)

        db_users = pd.DataFrame(db_users_list, columns=column_names)
        db_users.drop(columns=["is_blocking"])
        db_users.sort_values(by="name", inplace=True)
        db_users = db_users[col_order]
        print(db_users)
        print(az_users)

        # SECTION check for exact match
        exact_match = az_users.equals(db_users)

        if exact_match:
            print("no changed")

        else:
            print("changes made")
        
            # create 2 dataframes to compare
            old_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "right_only"').drop(columns='_merge')
            new_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "left_only"').drop(columns='_merge')

            old_users = old_users.replace({np.nan: None})
            new_users = new_users.replace({np.nan: None})

            old_users_tuples = [name for name in old_users['name']]
            new_users_tuples = [tuple(new_user) for new_user in new_users.values]

            # logger.info(old_users_tuples)
            # logger.info(new_users_tuples)
            
            # NEED APP CONTEXT

            for name in old_users_tuples:
                try:
                    User.query.filter_by(name=name).delete()
                except Exception as e:
                    db.session.rollback()
                    self.task_status = FAILED
            db.session.commit()

            for name, number, dept, _, is_global_admin, is_dept_admin in new_users_tuples:
                new_user = User(name=name, number=number, dept=dept, is_global_admin=is_global_admin, is_dept_admin=is_dept_admin)
                try:
                    db.session.add(new_user)
                except Exception as e:
                    db.session.rollback()
                    new_affected_users = list(az_users.loc[(az_users.reporting_officer_name == name), "name"])
                    self.failed_users.extend(name)
                    self.affected_users.extend(new_affected_users)
                    self.task_status = FAILED
            db.session.commit()

            for name, _, _, reporting_officer, _, _ in new_users_tuples:
                user = User.query.filter_by(name=name).first()
                try:
                    user.reporting_officer_name = reporting_officer
                except Exception as e:
                    db.session.rollback()
                    self.logger.info(traceback.format_exc())
                    self.task_status = FAILED
            db.session.commit()

    def update_table_urls(self):
        
        table_url_dict = {}

        if os.path.exists('/home/app/web/logs/table_urls.json') and os.path.getsize('/home/app/web/logs/table_urls.json') > 0:
            try:
                with open('/home/app/web/logs/table_urls.json', 'r') as file:
                    table_url_dict = json.loads(file.read())
            except json.JSONDecodeError:
                self.logger.info(traceback.format_exc())

        changed = False
        current_month = current_sg_time().month
        current_year = current_sg_time().year

        for mmyy, url in list(table_url_dict.items()):  # Use list() to avoid RuntimeError
            month_name, year = mmyy.split("-")
            month = datetime.strptime(month_name, "%B").month
            if (int(year) == current_year and current_month > month) or int(year) < current_year:
                table_url_dict.pop(mmyy)
                changed = True
            else:
                response = requests.get(url=url, headers=self.header)
                if response.status_code != 200:
                    table_url_dict.pop(mmyy)
                    changed = True

        if changed:
            self.logger.info("File has changed")
            with open("/home/app/web/logs/table_urls.json", 'w') as file:
                file.write(json.dumps(table_url_dict, indent=4))    

    def main(self):
        self.update_user_database()

        if self.task_status == OK:
            body = "User database was successfully updated"
        else:
            body = "Something went wrong with the sync."
            if len(self.failed_users) > 0: # FAILED
                body += f"Error updating details for {join_with_commas_and(self.failed_users)}."
            if len(self.affected_users) > 0:
                body += f"Affected users: {join_with_commas_and(self.affected_users)}."
        
        self.update_table_urls() # TO review

        return body
        

    
