import os
from sqlalchemy.exc import IntegrityError

import requests
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import traceback
from datetime import datetime
import json

from .utils import acquire_token, generate_header
from extensions import db
from models.users import User
from models.messages import MessageSent
from models.messages.abstract import Message
from app import app
from utilities import current_sg_time
from logs.config import setup_logger
from constants import messages


logger = setup_logger('az.users_sync', 'users_sync.log')

def sync_user_info():

    '''Returns a 2D list containing the user details within the inner array'''

    USERS_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/MainTable/tables/MainTable/rows"


    headers = generate_header()

    # print(manager.headers)

    # Make a GET request to the provided url, passing the access token in a header

    response = requests.get(url=USERS_TABLE_URL, headers=headers)
    data = [tuple(info) for object_info in response.json()['value'] for info in object_info['values']]

    # print(lookups_arrs)

    # print(f"user info: {user_arrs}")

    return data # info is already a list so user_info is a 2D list



def df_replace_spaces(df):
    '''removes the blank rows in the dataframe'''
    df.replace('', np.nan, inplace=True)
    df = df.dropna(how="all", inplace=True)
    return df

def update_user_database():

    col_order = ['name', 'number', 'dept', 'reporting_officer_name', 'is_global_admin', 'is_dept_admin']

    # SECTION AZURE SIDE
    data = sync_user_info()

    az_users = pd.DataFrame(data=data, columns=["name", "number", "dept", "reporting_officer_name", "access"])
    df_replace_spaces(az_users)
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

    # SECTION DB SIDE
    with app.app_context():
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
        print("no change")
    else:
        print("changes")

    if not exact_match:
        # create 2 dataframes to compare
        old_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "right_only"').drop(columns='_merge')
        new_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "left_only"').drop(columns='_merge')

        old_users = old_users.replace({np.nan: None})
        new_users = new_users.replace({np.nan: None})

        old_users_tuples = [name for name in old_users['name']]
        new_users_tuples = [tuple(new_user) for new_user in new_users.values]

        # logger.info(old_users_tuples)
        # logger.info(new_users_tuples)

        with app.app_context():
            try:
                for name in old_users_tuples:
                    User.query.filter_by(name=name).delete()

                for name, number, dept, _, is_global_admin, is_dept_admin in new_users_tuples:
                    
                    try:
                        new_user = User(name=name, number=number, dept=dept, is_global_admin=is_global_admin, is_dept_admin=is_dept_admin)
                        db.session.add(new_user)
                        db.session.commit()
                    except IntegrityError as e:
                        db.session.rollback()
                        affected_users = list(az_users.loc[(az_users.reporting_officer_name == name), "name"])
                        # Replace Chatbot.send_error_msg with your error handling logic
                        body = f"Error updating {name}'s details. {name} has been removed from the database. Affected users: {', '.join(affected_users)}"
                        # MessageSent.send_msg(body)
                        #TODO make a job if possible to sync with power automate and update upon file update
                        logger.error(body)
                        logger.info(traceback.format_exc())
                    except Exception as e:
                        db.session.rollback()
                        logger.info(traceback.format_exc())

                for name, _, _, reporting_officer, _, _ in new_users_tuples:
                    try:
                        user = User.query.filter_by(name=name).first()
                        if user:
                            user.reporting_officer_name = reporting_officer
                            db.session.commit()
                    except IntegrityError as e:
                        db.session.rollback()
                        logger.info(traceback.format_exc())
                    except Exception as e:
                        db.session.rollback()
                        logger.info(traceback.format_exc())

            except Exception as e:
                db.session.rollback()
                logger.info(traceback.format_exc())

        
def update_table_urls():
    
    table_url_dict = {}

    if os.path.exists('/home/app/web/logs/table_urls.json') and os.path.getsize('/home/app/web/logs/table_urls.json') > 0:
        try:
            with open('/home/app/web/logs/table_urls.json', 'r') as file:
                table_url_dict = json.loads(file.read())
        except json.JSONDecodeError:
            logger.info(traceback.format_exc())

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
            response = requests.get(url=url, headers=generate_header())
            if response.status_code != 200:
                table_url_dict.pop(mmyy)
                changed = True

    if changed:
        logger.info("File has changed")
        with open("/home/app/web/logs/table_urls.json", 'w') as file:
            file.write(json.dumps(table_url_dict, indent=4))

def main():
    
    acquire_token()

    update_user_database()

    update_table_urls()
            
        
if __name__ == "__main__":
    main()
