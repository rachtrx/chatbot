import os
from extensions import db
import msal

import requests
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import traceback
import sqlite3
from config import manager
import datetime

from models.chatbot import Chatbot

db_path = os.path.join(os.path.dirname(__file__), 'chatbot.db')

# Enter details of AAD app registration

config = {
    'client_id': os.environ.get('CLIENT_ID'),
    'client_secret': os.environ.get('CLIENT_SECRET'),
    'authority': os.environ.get('AUTHORITY'),
    'scope': [os.environ.get('SCOPE')],
    'site_id': os.environ.get('SITE_ID'),
}

# create an MSAL instance providing the client_id, authority and client_credential params
msal_instance = msal.ConfidentialClientApplication(config['client_id'], authority=config['authority'], client_credential=config['client_secret'])

def acquire_token(scope=config['scope']):
    # First, try to lookup an access token in cache
    token_result = msal_instance.acquire_token_silent(scope, account=None)
    # print("retrieving token")

    # If the token is available in cache, save it to a variable
    if token_result:
        print('Access token was loaded from cache')

    # If the token is not available in cache, acquire a new one from Azure AD and save it to a variable
    if not token_result:
        token_result = msal_instance.acquire_token_for_client(scopes=scope)
        # print(token_result)
        access_token = 'Bearer ' + token_result['access_token']

        print(f"Live env: {os.environ.get('LIVE')}")

        if os.environ.get('LIVE') == '1':
            # write the token to the file if on live, otherwise just use the token printed for postman
            print(f"Token path: {os.environ.get('TOKEN_PATH')}")
            with open(os.environ.get('TOKEN_PATH'), 'w') as file:
                file.write(access_token)

    return

def sync_user_info():
    '''Returns a 2D list containing the user details within the inner array'''

    USERS_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/Users/tables/UsersTable/rows"
    LOOKUP_TABLE_URL = f"https://graph.microsoft.com/v1.0/drives/{os.environ.get('DRIVE_ID')}/items/{os.environ.get('USERS_FILE_ID')}/workbook/worksheets/Lookup/tables/LookupTable/rows"

    # print(manager.headers)

    # Make a GET request to the provided url, passing the access token in a header
    users_request = requests.get(url=USERS_TABLE_URL, headers=manager.headers)
    lookups_request = requests.get(url=LOOKUP_TABLE_URL, headers=manager.headers)
    user_arrs = [tuple(info) for object_info in users_request.json()['value'] for info in object_info['values']]
    lookups_arrs = [tuple(info) for object_info in lookups_request.json()['value'] for info in object_info['values']]

    # print(lookups_arrs)

    # print(f"user info: {user_arrs}")

    return (user_arrs, lookups_arrs) # info is already a list so user_info is a 2D list



def df_replace_spaces(df):
    '''removes the blank rows in the dataframe'''
    df.replace('', np.nan, inplace=True)
    df = df.dropna(how="all", inplace=True)
    return df

def main():

    acquire_token(config['scope'])

    col_order = ['name', 'number', 'dept', 'email', 'reporting_officer_name', 'hod_name']

    # SECTION AZURE SIDE
    tables = sync_user_info()

    users = pd.DataFrame(data=tables[0], columns=["name", "number", "dept", "email"])
    df_replace_spaces(users)
    # print(users)
    try:
        users['number'] = users["number"].astype(int)
    except:
        nan_mask = users["number"].isna()
        nan_names = users.loc[nan_mask, 'name']
        names_arr = nan_names.values
        body = f"The phone number is missing for {', '.join(names_arr)}"
        Chatbot.send_error_msg(body)

    lookups = pd.DataFrame(data = tables[1], columns=["name", "reporting_officer_name", "hod_name"])
    df_replace_spaces(lookups)

    az_users = users.merge(lookups, how="outer", left_on="name", right_on="name", indicator=True)
    az_users = az_users[az_users._merge != "right_only"].drop(columns="_merge")
    az_users.sort_values(by="name", inplace=True)
    az_users = az_users[col_order]

    # SECTION DB SIDE
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''SELECT * FROM user ORDER BY name ASC''')
    db_users = cursor.fetchall()
    column_names = [description[0] for description in cursor.description]

    db_users = pd.DataFrame(db_users, columns=column_names)
    az_users.sort_values(by="name", inplace=True)
    db_users = db_users[col_order]

    # SECTION check for exact match
    exact_match = az_users.equals(db_users)

    if not exact_match:
        # create 2 dataframes to compare
        old_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "right_only"').drop(columns='_merge')
        new_users = pd.merge(az_users, db_users, how="outer", indicator=True).query('_merge == "left_only"').drop(columns='_merge')

        update_users = new_users[new_users.name.isin(old_users.name)]

        old_users = old_users[~old_users.name.isin(update_users.name)]
        new_users = new_users[~new_users.name.isin(update_users.name)]

        update_users_tuples = [tuple(update_user) for update_user in update_users.values]
        old_users_tuples = [tuple(old_user) for old_user in old_users.values]
        new_users_tuples = [tuple(new_user) for new_user in new_users.values]
        # print(old_users_tuples)
        # print(new_users_tuples)


        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            for name, number, dept, email, reporting_officer, hod in old_users_tuples:
                cursor.execute('DELETE FROM user WHERE name = ?', (name, ))
            
            conn.commit()
            conn.close()
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")

            for name, number, dept, email, reporting_officer, hod in new_users_tuples:
                cursor.execute('INSERT INTO user (name, number, dept, email) VALUES (?, ?, ?, ?)', (name, number, dept, email))

            conn.commit()
            conn.close()

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
                
            for name, number, dept, email, reporting_officer, hod in update_users_tuples:
                cursor.execute('UPDATE user SET number = ?, dept = ?, email = ?, reporting_officer_name = ?, hod_name = ? WHERE name = ?', (number, dept, email, reporting_officer, hod, name))

            for name, number, dept, email, reporting_officer, hod in new_users_tuples:
                cursor.execute('UPDATE user SET reporting_officer_name = ?, hod_name = ? WHERE name = ?', (reporting_officer, hod, name))

            conn.commit()
            conn.close()
            
        except Exception as e:
            conn.commit()
            conn.close()
            Chatbot.send_error_msg()
            tb = traceback.format_exc()
            print(f"Error: {e}")
            print(tb)

if __name__ == "__main__":
    print(f" Live: {os.environ.get('LIVE')}")
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=env_path)
    main()
