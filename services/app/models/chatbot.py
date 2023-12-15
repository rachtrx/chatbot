from utilities import loop_relations, join_with_commas_and
from constants import errors, PENDING_FORWARD_STATUS, PENDING_REPLY_STATUS, CONFIRM, CANCEL, FAILED, DURATION_CONFLICT
from datetime import datetime
import json
from models import ForwardMessage, Message
import os
from config import client

# def messaging_response(func):
#     def wrapper(*args, **kwargs):
#         resp = MessagingResponse()
#         response = func(*args, **kwargs)
#         resp.message(response)
#         return

#     return wrapper

class Chatbot:

    @staticmethod
    def fetch_message(sid):
        message = client.messages(sid).fetch()

        return message.body

    @staticmethod
    def send_mc_message(message):

        @loop_relations
        def generate_each_message(relation):
            '''This function sets up the details of the forward to HOD and reporting officer message'''
            
            # body = f'Hi {relation.name}! This is to inform you that {message.user.name} will be taking {message.duration} days MC from {message.start_date} to {message.end_date}'

            print(f"Type of date in notify: {type(message.start_date)}")


            content_variables = json.dumps({
                '1': relation.name,
                '2': message.user.name,
                '3': str(message.duration),
                '4': datetime.strftime(message.start_date, "%d/%m/%Y"),
                '5': datetime.strftime(message.end_date, "%d/%m/%Y")
            })

            
            return (content_variables, relation)
        
        content_variables_list = generate_each_message(message.user)
        print(f'content variables List: {content_variables_list}')
        return content_variables_list
    
    @staticmethod
    def confirm_mc_check(job):
        '''This function gets a mc_details object and returns a confirmation job to the person taking the MC'''

        print(f"Type of date in confirm: {type(job.start_date)}")

        # statement = f"Hi {job.user.name}, Kindly confirm that you are on MC for {job.duration} days from {datetime.strftime(job.start_date, '%d/%m/%Y')} to {datetime.strftime(job.end_date, '%d/%m/%Y')}. I will help you to inform "

        @loop_relations
        def generate_each_relation(relation):

            # return [relation.name, str(relation.number)]
            return [relation.name, str(relation.number)]
        
        data_list = generate_each_relation(job.user)

        if data_list == None:
            return None

        # list of return statements
        # else:
        #     statement += join_with_commas_and(data_list)

        content_variables = {
            '1': job.user.name,
            '2': str(job.duration),
            '3': datetime.strftime(job.start_date, '%d/%m/%Y'),
            '4': datetime.strftime(job.end_date, '%d/%m/%Y'),
        }

        if len(data_list) > 0:
            
            user_list = []
            for name, number in data_list:
                user_list.append(f"{name} ({number})")

            content_variables['5'] = join_with_commas_and(user_list)
            content_variables['6'] = str(CONFIRM)
            content_variables['7'] = str(CANCEL)

            content_variables = json.dumps(content_variables)

            return content_variables

        return None

    @staticmethod
    def reply_to_query(result, user):

        print(f"reply to query result: {result}")

        content_variables = {
                '1': user.name,
            }

        count = 2
        if len(result) > 0:
            for data, filename, url in result:
                content_variables[str(count)] = data
                content_variables[str(count + 1)] = f"[{filename}]({url})"
                count += 2

            content_variables = json.dumps(content_variables)


            return content_variables

    @staticmethod
    def send_template_msg(client, to_no, content_sid, content_variables=None):

        print(content_variables)

        sent_message_meta = client.messages.create(
                to=to_no,
                from_=os.environ.get("MESSAGING_SERVICE_SID"),
                content_sid=content_sid,
                content_variables=content_variables if content_variables is not None else {}
            )

        return sent_message_meta

    @classmethod
    def reply_template_msg(cls, message, content_sid, content_variables=None, status=PENDING_REPLY_STATUS):
        '''Creates the reply message, and sends the message. The reply status is either PENDING_REPLY_STATUS or PENDING_REPLY_STATUS_PENDING_USER_REPLY, if the user is expected to reply'''

        job = message.job

        replied_message_meta = cls.send_template_msg(client, job.user.sg_number, content_sid, content_variables)

        message.commit_reply_sid(replied_message_meta)

        # Message is always pending reply but job might be pending user reply next
        message.commit_status(status)

        job.commit_status(PENDING_REPLY_STATUS)
        
    @classmethod
    def forward_template_msg(cls, content_variables_and_users_list, job, content_sid, new_message):

        for content_variables, relation in content_variables_and_users_list:
            forward_message_meta = cls.send_template_msg(client, relation.sg_number, content_sid, content_variables)

            forward_message = ForwardMessage(job.job_number, forward_message_meta.sid, None, relation.name, new_message.sid)
            new_message.commit_status(PENDING_FORWARD_STATUS)
            forward_message.commit_status(PENDING_FORWARD_STATUS)
    
        job.commit_status(PENDING_FORWARD_STATUS)
    
    @staticmethod
    def reply_normal_msg(message, reply, message_status=PENDING_REPLY_STATUS, to_no=None):
        '''In reply messages, if the job isn't FAILED then the reply and job should both update to PENDING_REPLY_STATUS. But if the job is FAILED, then the reply might be PENDING_ERROR_REPLY_STATUS or PENDING_REPLY_STATUS but the job should remain FAILED'''
        job = message.job

        if to_no == None:
            number = job.user.sg_number
        else:
            number = to_no

        replied_message_meta = client.messages.create(
                from_=os.environ.get("TWILIO_NO"),
                to=number,
                body=reply
            )
        
        if job.status != FAILED and job.status != CANCEL and job.status != DURATION_CONFLICT:
            job.commit_status(PENDING_REPLY_STATUS)

        message.commit_reply_sid(replied_message_meta)
        message.commit_status(message_status)

        return 
    
    def send_error_msg(body="Something went wrong with the sync"):
        client.messages.create(
            from_=os.environ.get("TWILIO_NO"),
            to=os.environ.get("TEMP_NO"),
            body=body
        )