from models.jobs.system.abstract import JobSystem
import os

import requests
import pandas as pd
import numpy as np
import traceback

from azure.utils import generate_header
from extensions import db, get_session
from models.users import User
from models.exceptions import AzureSyncError

from logs.config import setup_logger
from utilities import join_with_commas_and
import logging

class JobSyncUsers(JobSystem):

    logger = setup_logger('models.job_sync_users')

    __tablename__ = 'job_sync_users'

    job_no = db.Column(db.ForeignKey("job_system.job_no", ondelete='CASCADE'), primary_key=True)
    
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

        # logging.info(manager.headers)

        # Make a GET request to the provided url, passing the access token in a header

        response = requests.get(url=USERS_TABLE_URL, headers=self.header)

        try:
            data = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
        except KeyError:
            raise AzureSyncError("Connection to Azure failed")

        # logging.info(lookups_arrs)

        # logging.info(f"user info: {user_arrs}")

        return data # info is already a list so user_info is a 2D list

    @staticmethod
    def df_replace_spaces(df):
        '''Replaces empty strings with NaN, removes entirely blank rows, and sets empty aliases to names.'''
        df = df.replace('', np.nan)
        df = df.dropna(how="all")
        df['alias'] = df.apply(lambda x: x['name'] if x['alias'] == '' else x['alias'], axis=1)
        return df

    def update_user_database(self):

        session = get_session()

        col_order = ['name', 'alias', 'number', 'dept', 'reporting_officer_name', 'is_global_admin', 'is_dept_admin']

        # SECTION AZURE SIDE
        data = self.sync_user_info()

        az_users = pd.DataFrame(data=data, columns=["name", "alias", "number", "dept", "reporting_officer_name", "access"])
        az_users = self.df_replace_spaces(az_users)

        # logging.info(users)
        try:
            az_users['number'] = az_users["number"].astype(int)
        except:
            nan_mask = az_users["number"].isna()
            nan_names = az_users.loc[nan_mask, 'name']
            names_arr = nan_names.values
            self.failed_users = join_with_commas_and(names_arr)
            self.logger.error(f"Failed to sync because of: {self.failed_users}")
            raise Exception

        az_users['is_global_admin'] = (az_users['access'] == 'GLOBAL')
        az_users['is_dept_admin'] = (az_users['access'] == 'DEPT')
        az_users.drop(columns=["access"])
        az_users.sort_values(by="name", inplace=True)
        az_users = az_users[col_order]

        # SECTION DB SIDE, need app context
        db_users = session.query(User).order_by(User.name).all()  # ORM way to fetch users
        db_users_list = [[user.name, user.alias, user.number, user.dept, user.reporting_officer_name, user.is_global_admin, user.is_dept_admin] for user in db_users]
        column_names = [column.name for column in User.__table__.columns]
        self.logger.info("%s %s", column_names, db_users_list)

        db_users = pd.DataFrame(db_users_list, columns=column_names)
        self.logger.info(db_users.dtypes)
        db_users.sort_values(by="name", inplace=True)
        db_users = db_users[col_order]

        pd.set_option('display.max_columns', None)
        self.logger.info(db_users)
        self.logger.info(az_users)

        # SECTION check for exact match
        exact_match = az_users.equals(db_users)

        if exact_match:
            self.logger.info("no changes")

        else:
            self.logger.info("changes made")
        
            # create 2 dataframes to compare
            merged_data = pd.merge(az_users, db_users, how="outer", indicator=True)
            old_data = merged_data[merged_data['_merge'] == 'right_only']
            new_data = merged_data[merged_data['_merge'] == 'left_only']

            old_names = [name for name in old_data['name']]
            new_names = [name for name in new_data['name']]
            updated_names = list(set(old_names).intersection(set(new_names)))

            updated_data = new_data.loc[new_data['name'].isin(updated_names)]
            updated_data = updated_data.replace({pd.NA: None, pd.NaT: None, "": None})

            old_data = old_data.loc[(old_data['name'].isin(old_names)) & ~(old_data['name'].isin(updated_names))]
            old_data = old_data.replace({pd.NA: None, pd.NaT: None, "": None})

            new_data = new_data.loc[(new_data['name'].isin(new_names)) & ~(new_data['name'].isin(updated_names))]
            new_data = new_data.replace({pd.NA: None, pd.NaT: None, "": None})

            updated_data = updated_data.drop(columns=['_merge'])
            old_data = old_data.drop(columns=['_merge'])
            new_data = new_data.drop(columns=['_merge'])

            updated_users_tuples = [tuple(updated_user) for updated_user in updated_data.values]
            old_users = [name for name in old_data['name']]
            new_users_tuples = [tuple(new_user) for new_user in new_data.values]
            
            self.logger.info(f"Updated users: {updated_data['name'].values}")
            self.logger.info(f"Old users: {old_data['name'].values}")
            self.logger.info(f"New users: {new_data['name'].values}")
            # NEED APP CONTEXT

            for name in old_users:
                try:
                    session.query(User).filter_by(name=name).delete()
                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    session.rollback()
                    self.error = True
            session.commit()

            self.logger.info("removed old")

            for name, alias, number, dept, _, is_global_admin, is_dept_admin in updated_users_tuples:
                try:
                    existing_user = session.query(User).filter(User.name == name).first()
                    
                    if existing_user:
                        existing_user.alias = alias
                        existing_user.number = number
                        existing_user.dept = dept
                        existing_user.is_global_admin = is_global_admin
                        existing_user.is_dept_admin = is_dept_admin
                    else:
                        self.logger.info(f"User {name} not found for update.")
                    session.commit()
                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    session.rollback()
                    new_affected_users = list(az_users.loc[az_users.reporting_officer_name == name, "name"])
                    self.failed_users.extend([name])
                    self.affected_users.extend(new_affected_users)
                    self.error = True

            for name, alias, number, dept, _, is_global_admin, is_dept_admin in new_users_tuples:
                new_user = User(name=name, alias=alias, number=number, dept=dept, is_global_admin=is_global_admin, is_dept_admin=is_dept_admin)
                try:
                    session.add(new_user)
                    session.commit()
                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    session.rollback()
                    new_affected_users = list(az_users.loc[(az_users.reporting_officer_name == name), "name"])
                    self.failed_users.extend(name)
                    self.affected_users.extend(new_affected_users)
                    self.error = True
            
            new_users_tuples.extend(updated_users_tuples)

            for name, _, _, _, reporting_officer, _, _ in new_users_tuples:
                user = session.query(User).filter_by(name=name).first()
                try:
                    user.reporting_officer_name = reporting_officer
                    session.commit()
                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    session.rollback()
                    self.error = True

            self.logger.info("added new")

    def main(self):
        self.logger.info("IN SYNC USERS")
        try:
            self.update_user_database()

            if not self.error:
                self.reply = "Sync was successful"
            else:
                self.reply = "Sync failed"
                if len(self.failed_users) > 0:
                    self.reply += f". Issues: {join_with_commas_and(self.failed_users)}"
                if len(self.affected_users) > 0:
                    self.reply += f". Affected: {join_with_commas_and(self.affected_users)}"
        except AzureSyncError as e:
            self.logger.error(e.message)
            self.reply = "Error connecting to Azure."
            self.error = True

        

    
