from psycopg2.extras import NamedTupleCursor
import shortuuid
import psycopg2
import os

conn = psycopg2.connect(
    dbname="chatbot",
    user=os.getenv('SQL_USER'),
    password=os.getenv('PGPASSWORD'),
    host="db"
)

# USERS
cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute("SELECT * FROM users")
records = cur.fetchall()

# Insert new users into the new_users table
for record in records:
    user_id = shortuuid.ShortUUID().random(length=8).upper()
    try:
        cur.execute(
            "INSERT INTO new_users (id, name, alias, number, dept, is_active, is_global_admin, is_dept_admin) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (user_id, record.name, record.alias, record.number, record.dept, 'true', record.is_global_admin, record.is_dept_admin)
        )
    except Exception as e:
        print(e)

conn.commit()

# Update reporting officer ID for each user
for record in records:
    if record.reporting_officer_name:
        cur.execute(
            "SELECT new_users.id FROM new_users WHERE new_users.name = %s",
            (record.reporting_officer_name,)
        )
        ro_id_result = cur.fetchone()
        if ro_id_result:
            ro_id = ro_id_result.id  # Assuming the fetched result is a NamedTuple and id is the column name
            try:
                cur.execute(
                    "UPDATE new_users SET reporting_officer_id = %s WHERE name = %s",
                    (ro_id, record.name)
                )
            except Exception as e:
                print(e)

conn.commit()
cur.close()


# GET JOB LEAVE
cur = conn.cursor(cursor_factory=NamedTupleCursor)

leave_type_map = {
    'Medical': 'MEDICAL',
    'Childcare': 'CHILDCARE',
    'Parentcare': 'PARENTCARE',
    'Hospitalisation': 'HOSPITALISATION',
    'Compassionate': 'COMPASSIONATE'
}

cur.execute("SELECT job.job_no, job.status, job.created_at, new_users.name, new_users.id, job_leave.leave_type FROM job JOIN job_user ON job_user.job_no = job.job_no JOIN job_leave ON job_user.job_no = job_leave.job_no JOIN new_users ON job_user.name = new_users.name") # TODO check if correct join

# Retrieve query results
records = cur.fetchall()

for record in records:
    try:
        cur.execute(
            "INSERT INTO new_job (job_no, created_at, primary_user_id, type) VALUES (%s, %s, %s, %s)",
            (record.job_no, record.created_at, record.id, 'LEAVE') # TODO
        )
        cur.execute(
            "INSERT INTO new_job_leave (job_no, error, leave_type) VALUES (%s, %s, %s)",
            (record.job_no, 'UNKNOWN' if record.status != 200 else None, leave_type_map.get(record.leave_type))
        )
        if record.status == 200:
            cur.execute(
                "SELECT leave_records.is_cancelled FROM leave_records WHERE leave_records.job_no = %s ORDER BY date DESC LIMIT 1",
                (record.job_no,)
            )
            last_date = cur.fetchone()
            if last_date is None:
                continue
            task_type = 'CANCEL' if last_date.is_cancelled else 'CONFIRM' # NOT APPROVE
            new_id = shortuuid.ShortUUID().random(length=8).upper()
            cur.execute(
                "INSERT INTO task_leave (id, type, job_no, created_at, status, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (new_id, task_type, record.job_no, record.created_at, 'COMPLETED', record.id)
            )
    except Exception as e:
        print(e)

conn.commit()
cur.close()


# MOVE DAEMON JOBS

cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute("SELECT job.job_no, job.status, job.created_at, job.type, new_users.name, new_users.id FROM job JOIN job_system ON job_system.job_no = job.job_no JOIN new_users ON job_system.root_name = new_users.name ORDER BY job.created_at")
records = cur.fetchall()

task_type_map = {
    'job_acq_token': 'ACQUIRE_TOKEN',
    'job_sync_users': 'SYNC_USERS',
    'job_sync_records': 'SYNC_LEAVES',
    'job_am_report': 'SEND_REPORT'
}

current_job_no = None
for record in records:
    # status can be 102, 200 or 402
    try:
        if record.type == 'job_system': # BASE
            current_job_no = record.job_no

            cur.execute(
                "INSERT INTO new_job (job_no, created_at, primary_user_id, type) VALUES (%s, %s, %s, %s)",
                (record.job_no, record.created_at, record.id, 'DAEMON') # TODO
            )
            cur.execute(
                "INSERT INTO job_daemon (job_no) VALUES (%s)",
                (record.job_no, )
            )
        else:
            task_type = task_type_map.get(record.type)
            if not current_job_no or not task_type:
                continue
            new_id = shortuuid.ShortUUID().random(length=8).upper()
            cur.execute(
                "INSERT INTO task_daemon (id, type, job_no, created_at, status, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (new_id, task_type, current_job_no, record.created_at, 'FAILED' if record.status == 402 else 'COMPLETED', record.id)
            )
    except Exception as e:
        print(e)

conn.commit()
cur.close()


####################
# SECTION MESSAGES
####################

msg_type_map = {
    'message_sent': 'SENT',
    'message_received': 'RECEIVED',
    'message_forward': 'FORWARD',
    'message_confirm': 'RECEIVED'
}

# GET MESSAGE KNOWN

cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute('''SELECT 
        message.sid, 
        message.type, 
        message.body, 
        message.timestamp, 
        message.seq_no, 
        message.job_no, 
        new_users.id 
    FROM 
        message 
    JOIN 
        job ON job.job_no = message.job_no 
    JOIN 
        job_user ON job_user.job_no = message.job_no 
    JOIN 
        new_users ON job_user.name = new_users.name 
    WHERE 
        job.type = 'job_leave'

    UNION

    -- Query for job_system type
    SELECT 
        message.sid, 
        message.type, 
        message.body, 
        message.timestamp, 
        message.seq_no, 
        message.job_no, 
        new_users.id
    FROM 
        message 
    JOIN 
        job ON job.job_no = message.job_no 
    JOIN 
        job_system ON job_system.job_no = job.job_no 
    JOIN 
        new_users ON job_system.root_name = new_users.name 
    WHERE 
        job.type = 'job_system'
''') # IMPT Dont get job_leave_cancel which is a child

# Retrieve query results
records = cur.fetchall()

for record in records:
    # status can be 102, 200 or 402
    try:
        cur.execute(
            "INSERT INTO new_message (sid, body, timestamp, type, msg_type) VALUES (%s, %s, %s, %s, %s)",
            (record.sid, record.body, record.timestamp, 'KNOWN', msg_type_map.get(record.type)) # TODO
        )
        if not record.type == 'message_forward':
            cur.execute(
                "INSERT INTO message_known (sid, job_no, user_id, seq_no) VALUES (%s, %s, %s, %s)",
                (record.sid, record.job_no, record.id, record.seq_no)
            )
        else:
            cur.execute("SELECT new_users.id FROM new_users JOIN message_forward ON message_forward.to_name = new_users.name WHERE message_forward.sid = %s", (record.sid, ))
            user_id = cur.fetchone()
            cur.execute(
                "INSERT INTO message_known (sid, job_no, user_id, seq_no) VALUES (%s, %s, %s, %s)",
                (record.sid, record.job_no, user_id, record.seq_no)
            )
        if record.type == 'message_sent' or record.type == 'message_forward':
            cur.execute("SELECT message_sent.status FROM message_sent WHERE message_sent.sid = %s", (record.sid, ))
            sent_msg = cur.fetchone()

            cur.execute(
                "INSERT INTO sent_message_status (sid, status) VALUES (%s, %s)",
                (record.sid, 'FAILED' if sent_msg.status == 402 else 'COMPLETED')
            )
    except Exception as e:
        print(e)

conn.commit()
cur.close()

# CANCEL MESSAGES
cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute("SELECT job_leave_cancel.initial_job_no, job_leave_cancel.job_no, MAX(message.seq_no) as max_seq_no FROM job_leave_cancel JOIN message ON message.job_no = job_leave_cancel.initial_job_no GROUP BY job_leave_cancel.initial_job_no, job_leave_cancel.job_no")

# Retrieve query results
records = cur.fetchall()

for record in records:
    # status can be 102, 200 or 402
    cur_seq_no = record.max_seq_no
    try:
        cur.execute("SELECT message.sid, message.type, message.body, message.timestamp, message.seq_no, new_users.id FROM message JOIN job_user ON job_user.job_no = message.job_no JOIN new_users ON job_user.name = new_users.name WHERE message.job_no = %s", (record.job_no,)) # TODO check if correct join

        messages = cur.fetchall()

        for message in messages:
            
            cur_seq_no += 1

            cur.execute(
                "INSERT INTO new_message (sid, body, timestamp, type, msg_type) VALUES (%s, %s, %s, %s, %s)",
                (message.sid, message.body, message.timestamp, 'KNOWN', msg_type_map.get(message.type)) # TODO
            )
            if not message.type == 'message_forward':
                cur.execute(
                    "INSERT INTO message_known (sid, job_no, user_id, seq_no) VALUES (%s, %s, %s, %s)",
                    (message.sid, record.initial_job_no, message.id, cur_seq_no)
                )
            else:
                cur.execute("SELECT new_users.id FROM new_users JOIN message_forward ON message_forward.to_name = new_users.name WHERE message_forward.sid = %s", (message.sid, ))
                user_id = cur.fetchone()
                cur.execute(
                    "INSERT INTO message_known (sid, job_no, user_id, seq_no) VALUES (%s, %s, %s, %s)",
                    (message.sid, record.initial_job_no, user_id, cur_seq_no)
                )
            if message.type == 'message_sent' or message.type == 'message_forward':
                cur.execute("SELECT message_sent.status FROM message_sent WHERE message_sent.sid = %s", (message.sid, ))
                sent_msg = cur.fetchone()

                cur.execute(
                    "INSERT INTO sent_message_status (sid, status) VALUES (%s, %s)",
                    (message.sid, 'FAILED' if sent_msg.status == 402 else 'COMPLETED')
                )
    except Exception as e:
        print(e)

conn.commit()
cur.close()

# LEAVE RECORDS: Some leave jobs whose user has resigned is unfortunately lost

cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute("SELECT lr.id, lr.job_no, lr.date, lr.sync_status, lr.is_cancelled FROM leave_records lr JOIN new_job_leave ON lr.job_no = new_job_leave.job_no")
records = cur.fetchall()

for record in records:
    # status can be 102, 200 or 402
    try:
        cur.execute(
            "INSERT INTO new_leave_records (id, job_no, date, sync_status, leave_status) VALUES (%s, %s, %s, %s, %s)",
            (record.id, record.job_no, record.date, 'FAILED' if record.sync_status == 402 else 'COMPLETED', 'CANCELLED' if record.is_cancelled else 'APPROVED') 
        )
    except Exception as e:
        print(e)

conn.commit()
cur.close()

# MESSAGE UNKNOWN

cur = conn.cursor(cursor_factory=NamedTupleCursor)

cur.execute("SELECT job_unknown.job_no, job_unknown.from_no, message.sid, message.body, message.timestamp, message.type, message.seq_no FROM job_unknown JOIN message ON message.job_no = job_unknown.job_no") # TODO check if correct join
records = cur.fetchall()

for record in records:
    # status can be 102, 200 or 402
    try:
        
        cur.execute(
            "INSERT INTO new_message (sid, body, timestamp, type, msg_type) VALUES (%s, %s, %s, %s, %s)",
            (record.sid, record.body, record.timestamp, 'UNKNOWN', msg_type_map.get(record.type))
        )
        idx = record.from_no.find('+')
        if idx != -1:
            user_no = record.from_no[idx:]
        else:
            user_no = record.from_no
        cur.execute(
            "INSERT INTO message_unknown (sid, user_no) VALUES (%s, %s)",
            (record.sid, user_no)
        )
        if record.type == 'message_sent' or record.type == 'message_forward':
            cur.execute("SELECT message_sent.status FROM message_sent WHERE message_sent.sid = %s", (message.sid, ))
            sent_msg = cur.fetchone()

            cur.execute(
                "INSERT INTO sent_message_status (sid, status) VALUES (%s, %s)",
                (record.sid, 'FAILED' if sent_msg.status == 402 else 'COMPLETED')
            )
    except Exception as e:
        print(e)

conn.commit()
cur.close()

conn.close()