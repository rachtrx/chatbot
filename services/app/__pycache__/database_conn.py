# This file is used for any interactions with the database

# import openpyxl
# import pandas as pd
# import sqlite3
# from datetime import datetime, timedelta
# import json
# import uuid
# from extensions import db
# from models import User, McDetails
# from sqlalchemy import desc

# SUCCESS = 1
# PENDING_USER_REPLY = 2
# FAILED = 3

# intents = {
#     "TAKE_MC": 1,
#     "OTHERS": 2
# }


# def get_cfm_mc_details(number):
#     '''Returns any pending message from the user within 1 hour'''
#     recent_msg = McDetails.query.filter_by(
#         number=number, 
#         status=PENDING_USER_REPLY, 
#         intent=intents["TAKE_MC"]
#     ).order_by(
#         desc(McDetails.timestamp)
#     ).first()

#     print(recent_msg)
    
#     if recent_msg:
#         timestamp = recent_msg.timestamp
#         current_time = datetime.now()
#         time_difference = current_time - timestamp
#         if time_difference < timedelta(hours=1):
#             user, reporting_officer, hod = get_user_info(number)
#             final_arr = [user, reporting_officer, hod, recent_msg]
#             recent_msg.status = SUCCESS
#             db.session.commit()
#             return final_arr
        
#     return False



# def add_mc_message(mc_details, user): 
#     message_id = uuid.uuid4().hex
#     start_date, end_date, duration = mc_details

#     new_mc_details = McDetails(
#         id=message_id,
#         number=user.number,
#         name=user.name,
#         start_date=start_date,
#         end_date=end_date, 
#         duration=duration,
#         intent=intents["TAKE_MC"],
#         status=PENDING_USER_REPLY,
#     )

#     db.session.add(new_mc_details)
#     db.session.commit()
    
#     return mc_details


# def get_user_info(from_number):
#     user = User.query.filter_by(
#         number=from_number
#     ).first()

#     if user:
#         return [user, user.reporting_officer, user.hod]
#     else:
#         return None
    

# @connect_to_db
# def get_name(cursor, phone):
#     cursor.execute('SELECT name FROM users WHERE number = ?', (phone,))
#     return None if name is None else name[0]