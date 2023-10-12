# This file is used for any interactions with the database

import openpyxl
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import json
import uuid

SUCCESS = 1
PENDING_USER_REPLY = 2
FAILED = 3

intents = {
    "TAKE_MC": 1,
    "OTHERS": 2
}

def connect_to_db(func):
    '''This decorator returns a wrapper that will start and stop the connection after running the database queries'''
    def wrapper(*args, **kwargs):
        conn = sqlite3.connect('chatbot.db')
        cursor = conn.cursor()
        result = func(cursor, *args, **kwargs)
        conn.commit()
        conn.close()
        return result
    return wrapper

# @connect_to_db
# def main(cursor):
#     # Create a users and messages table
#     cursor.execute('''CREATE TABLE IF NOT EXISTS users (name TEXT UNIQUE, number INTEGER UNIQUE, email TEXT UNIQUE, reporting_officer TEXT, hod TEXT)''')
#     cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id TEXT UNIQUE, number INTEGER, name TEXT, message TEXT, intent INTEGER, status INTEGER, timestamp DATETIME)''')

@connect_to_db
def get_cfm_mc_details(cursor, number):
    '''Returns any pending message from the user within 1 hour'''
    cursor.execute('SELECT * FROM mc_details WHERE number = ? AND status = ? AND intent = ? ORDER BY timestamp DESC LIMIT 1', (number, PENDING_USER_REPLY, intents["TAKE_MC"]))

    row = cursor.fetchall()
    print(row)
    
    if row:
        print(row)
        uuid, number, name, r_name, r_number, h_name, h_number, start_date, end_date, duration, intent, status, timestamp = row[0]
        timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
        current_time = datetime.now()
        time_difference = current_time - timestamp
        if time_difference < timedelta(hours=1):
            cursor.execute('UPDATE mc_details SET status = ? WHERE id = ?', (SUCCESS, uuid))
            return [name, r_name, r_number, h_name, h_number, start_date, end_date, duration]
        
    return False

@connect_to_db
def add_message(cursor, mc_details, user_info): 
    message_id = uuid.uuid4()
    name, number, email, r_name, r_number, r_email, h_name, h_number, h_email = user_info
    start_date, end_date, duration = mc_details

    cursor.execute("INSERT INTO mc_details (id, number, name, r_name, r_number, h_name, h_number, start_date, end_date, duration, intent, status, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(message_id), number, name, r_name, r_number, h_name, h_number, start_date, end_date, duration, intents["TAKE_MC"], PENDING_USER_REPLY, datetime.now()))
    
    return True
    

# @connect_to_db
# def get_name(cursor, phone):
#     cursor.execute('SELECT name FROM users WHERE number = ?', (phone,))
#     return None if name is None else name[0]


if __name__ == "__main__":
    main()