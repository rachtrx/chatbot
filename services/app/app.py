from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import os
from twilio.rest import Client

from spacy_input import check_for_intent, check_response
from azure_conn import get_user_info, get_msal_instance, config
from database_conn import get_old_message, add_message

app = Flask(__name__)

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
client = Client(account_sid, auth_token)

msal = get_msal_instance()

def general_workflow(request):

    message, from_number = get_message_details(request);
    user_info = get_user_info(from_number, msal, config['scope'])[0] # need to index 0 as this func returns a 2D list

    if check_response(str(message)):
        old_message = get_old_message(from_number);
        if old_message:
            mc_details = check_for_intent(old_message)
            send_message(mc_details, user_info)
            return False

    mc_details = check_for_intent(message)
    if mc_details:
        add_message(user_info, message)
        return generate_reply(mc_details, user_info)
    else:
        return "Sorry I did not get what you mean, or you have exceeded the 10 min timeout. Please let me know how many days of leave you are planning to take"

def send_message(mc_details, user_info):
    '''This function sets up the details of the forward to HOD and reporting officer message'''

    name, number, email, r_name, r_number, r_email, h_name, h_number, h_email = user_info
    days, start_date, end_date = mc_details

    to_numbers = [r_number, h_number] 

    # Define the message parameters
    for number in to_numbers:
        
        to_number = str(number)  # Original number
        from_number = 'whatsapp:+18155730824'  # Your Twilio number
        body = f'Hi! This is to inform you that {name} will be taking {days} days MC from {start_date} to {end_date}'

        # Send the message
        message = client.messages.create(
            to='whatsapp:+65' + to_number,
            from_=from_number,
            body=body
        )

    print(message.sid)
    return True

def get_message_details(request):

    print(request.form)


    user_str = request.form.get("Body")
    from_number = int(request.form.get("From")[-8:])

    print(from_number)
    print(f"Received {user_str}")

    return (user_str, from_number)


def generate_reply(mc_details, user_info):
    '''This function gets the user info and mc details and returns a confirmation message'''

    name, number, email, r_name, r_number, r_email, h_name, h_number, h_email = user_info
    days, start_date, end_date = mc_details

    return f"Hi {name}, Kindly confirm that you are on MC for {days} days from {start_date:%B %d} to {end_date:%B %d}. I will help you to inform {r_name} ({r_number}) and {h_name} ({h_number}) (Yes/No)"


@app.route("/chatbot/sms/test/", methods=['GET', 'POST'])
def sms_reply_test():
    """Respond to incoming calls with a simple text message."""

    response = general_workflow(request)

    return response

@app.route("/chatbot/sms/", methods=['GET', 'POST'])
def sms_reply():
    """Respond to incoming calls with a simple text message."""

    response = general_workflow(request)

    if response:
        # Start our TwiML response
        resp = MessagingResponse()

        # Add a message
        resp.message(response)

        print(str(resp))

        return str(resp)
    else:
        return "Message was a confirmation, now waiting for callback"


@app.route("/chatbot/sms/callback/", methods=['POST'])
def sms_reply_callback():
    """Respond to incoming calls with a simple text message."""

    status = request.form.get('MessageStatus')
    print(status)

    return True
    
    # TODO get the number and inform success

if __name__ == "__main__":
    app.run(debug=True)