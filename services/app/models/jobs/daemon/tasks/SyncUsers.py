import requests
import pandas as pd
import numpy as np
import shortuuid

from extensions import Session

from models.users import User
from models.exceptions import AzureSyncError

from models.jobs.base.utilities import join_with_commas_and

from models.jobs.daemon.Task import TaskDaemon
from models.jobs.daemon.constants import Link, DaemonTaskType, DaemonMessage
from models.jobs.daemon.utilities import generate_header

USER_COLS = ['name', 'alias', 'number', 'dept', 'is_global_admin', 'is_dept_admin', 'is_active']

class SyncUsers(TaskDaemon):

    name = "Users Sync"

    __mapper_args__ = {
        "polymorphic_identity": DaemonTaskType.SYNC_USERS
    }

    def execute(self):
        self.header = generate_header()
        self.failed_users = []
        self.affected_users = []

        try:
            self.update_user_database()
            self.body = DaemonMessage.SYNC_COMPLETED
        except AzureSyncError as e:
            self.logger.error(e)
            self.body = DaemonMessage.AZURE_CONN_FAILED
            raise
        
    def get_err_body(self) -> str:
        
        body = DaemonMessage.SYNC_FAILED
        if len(self.failed_users) > 0:
            body += ". Failed: " + [join_with_commas_and(self.failed_users)]
        if len(self.affected_users) > 0:
            body += ". Affected: " + [join_with_commas_and(self.affected_users)]
        return body

    def get_az_table_data(self):

        '''Returns a 2D list containing the user details within the inner array'''

        response = requests.get(url=Link.USERS_TABLE_URL, headers=self.header)

        try:
            data = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]
        except KeyError:
            raise AzureSyncError(DaemonMessage.AZURE_CONN_FAILED)

        self.logger.info(f"AZ Data: {data}")
        return data # info is already a list so user_info is a 2D list

    @staticmethod
    def clean_df(df):
        '''Replaces empty strings with NaN, removes entirely blank rows, and sets empty aliases to names.'''
        df = df.replace({np.nan: None, '': None })
        df = df.dropna(how="all")
        df.loc[df['alias'].isnull(), 'alias'] = df['name']
        df['number'] = df['number'].str.replace(' ', '', regex=True)
        return df

    def update_user_database(self):

        session = Session()

        # SECTION AZURE SIDE
        az_table_data = self.get_az_table_data()

        az_df = pd.DataFrame(
            data=az_table_data, 
            columns=["name", "alias", "number", "dept", "reporting_officer_name", "access"],
            dtype='string'
        )

        az_df = self.clean_df(az_df)

        # Set data types
        data_types = {
            'name': 'str',
            'alias': 'str',
            'number': 'int',
            'dept': 'str',
            'reporting_officer_name': 'str',
            'access': 'str',
        }

        for column, dtype in data_types.items():
            az_df[column] = az_df[column].astype(dtype)

        try:
            az_df['number'] = az_df["number"].astype(int)
        except:
            az_df['temp_number'] = pd.to_numeric(az_df['number'], errors='coerce')
            problematic_rows = az_df[az_df['temp_number'].isna()]
            self.failed_users.extend(join_with_commas_and(problematic_rows['name'].tolist()))
            raise Exception

        az_df['is_global_admin'] = (az_df['access'] == 'GLOBAL')
        az_df['is_dept_admin'] = (az_df['access'] == 'DEPT')
        # az_df['is_global_admin'] = az_df['is_global_admin'].astype('bool')
        # az_df['is_dept_admin'] = az_df['is_dept_admin'].astype('bool')
        az_df['is_active'] = True

        az_users = az_df[USER_COLS].copy() # need az_df for reporting officer later
        

        db_df = pd.read_sql(session.query(User).statement, session.bind)
        db_users = db_df[[*USER_COLS, 'id']].copy()

        # self.logger.info(f"azure users: {az_users}")
        # self.logger.info(f"db_users users: {db_users}")
        # self.logger.info(f"az_users columns: {az_users.columns}")
        # self.logger.info(f"db_users columns: {db_users.columns}")

        self.logger.info("checking for exact match")

        if not self.check_for_exact_match(az_users[USER_COLS], db_users.loc[db_users['is_active'] == True, USER_COLS]):

            self.logger.info("not exact match")

            MATCH_ON_COLS = ['name', 'number']

            # Perform the merge operation with indicators
            merged_users = pd.merge(
                az_users, 
                db_users,
                on=MATCH_ON_COLS,
                how="outer", 
                indicator=True,
                suffixes=('', '_old')
            )

            merged_users.replace({pd.NA: None, pd.NaT: None, "": None}, inplace=True)

            old_user_ids = merged_users.loc[(merged_users['_merge'] == 'right_only') & (merged_users['is_active_old'] == True), 'id']

            COLS_TO_COMPARE = [col for col in USER_COLS if col not in MATCH_ON_COLS] # 5 cols

            updated_users = merged_users.loc[(merged_users['_merge'] == 'both')]
            differences = pd.DataFrame({col: updated_users[f"{col}_old"] != updated_users[col] for col in COLS_TO_COMPARE}).any(axis=1)

            COLS_TO_UPDATE = ['id'] + [col for col in COLS_TO_COMPARE if col != 'is_active'] # 5 cols
            updated_users = updated_users.loc[differences, COLS_TO_UPDATE]
            updated_users_tuples = [tuple(updated_user) for updated_user in updated_users.values]

            COLS_TO_ADD = ['id'] + [col for col in USER_COLS if col != 'is_active'] # 7 cols
            new_users = merged_users.loc[merged_users['_merge'] == 'left_only', COLS_TO_ADD]
            new_users['id'] = [shortuuid.ShortUUID().random(length=8) for _ in range(len(new_users))]
            new_users_tuples = [tuple(new_user) for new_user in new_users.values]
            
            self.logger.info(f"Updating users.")
            self.logger.info(f"New users: {new_users_tuples}")
            self.logger.info(f"Updated users: {updated_users_tuples}")
            self.logger.info(f"Old user IDs: {old_user_ids}")

            session.bulk_update_mappings(User, [
                {'id': user_id, 'is_active': False, 'reporting_officer_id': None }
                for user_id in old_user_ids.values
            ])

            session.bulk_update_mappings(User, [
                {'id': user_id, 'alias': alias, 'dept': dept, 'is_global_admin': is_global_admin, 'is_dept_admin': is_dept_admin, 'is_active': True }
                for user_id, alias, dept, is_global_admin, is_dept_admin in updated_users_tuples
            ])

            session.bulk_insert_mappings(User, [
                {'id': user_id, 'name': name, 'alias': alias, 'number': number, 'dept': dept, 'is_global_admin': is_global_admin, 'is_dept_admin': is_dept_admin, 'is_active': True }
                for user_id, name, alias, number, dept, is_global_admin, is_dept_admin in new_users_tuples
            ])

            session.commit()

        # map the Reporting Officers
        az_ro_lookup = az_df[['name', 'reporting_officer_name']].copy()
        db_ro_lookup = pd.read_sql(session.query(User.name, User.id, User.reporting_officer_id).filter(User.is_active == True).statement, session.bind)

        name_to_id_map = dict(zip(db_ro_lookup['name'], db_ro_lookup['id']))
        az_ro_lookup['reporting_officer_id'] = az_ro_lookup['reporting_officer_name'].map(name_to_id_map)
        az_ro_lookup['id'] = az_ro_lookup['name'].map(name_to_id_map)

        az_ro_lookup = az_ro_lookup[['id', 'reporting_officer_id']]
        db_ro_lookup = db_ro_lookup[['id', 'reporting_officer_id']]

        az_ro_lookup = az_ro_lookup.where(pd.notna(az_ro_lookup), None) # Replace NaN values with None
        db_ro_lookup = db_ro_lookup.where(pd.notna(db_ro_lookup), None)

        # self.logger.info(f"az_ro_lookup: {az_ro_lookup}")
        # self.logger.info(f"db_ro_lookup: {db_ro_lookup}")
        self.logger.info("Checking exact match for RO")

        # SECTION check for exact match
        if not self.check_for_exact_match(az_ro_lookup, db_ro_lookup):

            self.logger.info("No exact match for RO")

            merged_lookups = pd.merge(
                az_ro_lookup, 
                db_ro_lookup,
                how="outer", 
                indicator=True,
            )

            self.logger.info(f"Lookups: {merged_lookups}")

            old_lookup_user_ids = merged_lookups.loc[merged_lookups['_merge'] == 'right_only', 'id']
            new_lookups = merged_lookups.loc[merged_lookups['_merge'] == 'left_only']

            new_lookup_tuples = [tuple(new_lookup) for new_lookup in new_lookups.values]

            self.logger.info(f"New lookups: {new_lookup_tuples}")
            self.logger.info(f"DB lookups: {old_lookup_user_ids}")

            session.bulk_update_mappings(User, [
                {'id': user_id, 'reporting_officer_id': None }
                for user_id in old_lookup_user_ids
            ])

            session.bulk_update_mappings(User, [
                {'id': user_id, 'reporting_officer_id': reporting_officer_id }
                for user_id, reporting_officer_id, _ in new_lookup_tuples
            ])
            
            session.commit()

            self.logger.info("Updated RO")
        
    def check_for_exact_match(self, df1, df2):

        if set(df1.columns) != set(df2.columns):
            self.logger.info("Columns are different")
            return False  # Return False if they do not have the same columns

        common_columns = list(df1.columns)
        df1 = df1[common_columns].sort_index(axis=1)
        df2 = df2[common_columns].sort_index(axis=1)

        df1_sorted = df1.sort_values(by=common_columns).reset_index(drop=True)
        df2_sorted = df2.sort_values(by=common_columns).reset_index(drop=True)

        # pd.set_option('display.max_columns', None)

        return df1_sorted.equals(df2_sorted)

    
