import re
from datetime import datetime, timedelta
import spacy
from word2number import w2n

import os
from twilio.rest import Client

# account_sid = os.environ['TWILIO_ACCOUNT_SID']
# auth_token = os.environ['TWILIO_AUTH_TOKEN']
# client = Client(account_sid, auth_token)

nlp = spacy.load("en_core_web_sm")

# SECTION general token prints
def print_token_details(doc):
    for token in doc:
        print(f'{token.text:{10}} {token.pos_:{10}} {token.ent_type_:{10}}')

# SECTION check for correct intent and no. of days
def get_days(offset):
    '''returns number of days, todays date, and the end date'''
    assert isinstance(offset, int)
    return [offset, datetime.now(), datetime.now() + timedelta(days = offset - 1)]

def check_date_ent(substring):
    # print(type(substring), substring)
    doc = nlp(substring)
    # print_token_details(doc)

    for ent in doc.ents:
        if ent.label_ == "DATE":
            for token in ent:
                if token.pos_ == "NUM":
                    return get_days(int(token.text))
                elif token.text.lower() == "today" or token.text.lower() == "a":
                    return get_days(1)
    return False

def check_for_intent(user_str):
    '''Function takes in a user input and if intent is not MC, it returns False. Else, it will return a list with the number of days, today's date and end date'''

    # 2 kinds of inputs: "I will be taking 2 days leave due to a medical appointment  mc vs I will be on medical leave for 2 days"
    full_absent_pattern = re.compile(r'\b(on|taking|take) (.*?((\d\d?\d?|a) (day|days)|today) .*?(leave|mc|appointment)|.*?(leave|mc|appointment) .*?((\d\d?\d?|a) (day|days)|today))\b', re.IGNORECASE)
    matches_list = list(full_absent_pattern.finditer(user_str))
    
    if len(matches_list) != 1:
        print("total numbers != 1!")
        return False #ambiguous
    
    print("1. match found")
    match = matches_list[0]
    mc_details = check_date_ent(match.group())
    return mc_details

def check_response(message):
    confirmation_pattern = re.compile(r'^(yes|no)$', re.IGNORECASE)
    
    if confirmation_pattern.match(message):
        return True
    return False

# SECTION sync with the excel file

def main():
    user_str = input("Hi what would you like to do? ")
    doc = nlp(user_str)
    print_token_details(doc)
    details = check_for_intent(user_str)
    if details:
        days, start_date, end_date = details
        print(f"Kindly confirm that you are on MC for {days} days from {start_date:%B %d} to {end_date:%B %d}")

    else:
        print("Sorry I did not get what you mean, please let me know how many days of leave you are planning to take")

if __name__ == "__main__":
    main()
