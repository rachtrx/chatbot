"""Migration #1 Create New Tables

Revision ID: 55183dbfb8e4
Revises: 9b2a00f6cdcc
Create Date: 2024-06-22 14:41:49.658577

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '55183dbfb8e4'
down_revision = '9b2a00f6cdcc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###

    op.create_table('new_message',
        sa.Column('sid', sa.String(length=64), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(length=10), nullable=False),
        sa.Column('msg_type', sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint('sid')
    )
    op.create_table('new_users',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('alias', sa.String(length=80), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('dept', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_global_admin', sa.Boolean(), nullable=False),
        sa.Column('is_dept_admin', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'number', name='_name_number_uc')
    )
    op.create_table('lookups',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=80), nullable=False),
        sa.Column('lookup_id', sa.String(length=80), nullable=False),
        sa.Column('is_reporting_officer', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['new_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lookup_id'], ['new_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'lookup_id', name='_user_lookup_uc')
    )
    op.create_table('message_unknown',
        sa.Column('sid', sa.String(length=64), nullable=False),
        sa.Column('user_no', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['sid'], ['new_message.sid'], ),
        sa.PrimaryKeyConstraint('sid')
    )
    op.create_table('new_job',
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('primary_user_id', sa.String(length=32), nullable=True),
        sa.Column('type', sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(['primary_user_id'], ['new_users.id'], ),
        sa.PrimaryKeyConstraint('job_no')
    )
    op.create_table('sent_message_status',
        sa.Column('sid', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(['sid'], ['new_message.sid'], ),
        sa.PrimaryKeyConstraint('sid')
    )
    op.create_table('job_daemon',
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['job_no'], ['new_job.job_no'], ),
        sa.PrimaryKeyConstraint('job_no')
    )
    op.create_table('message_known',
        sa.Column('sid', sa.String(), nullable=False),
        sa.Column('job_no', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(length=32), nullable=True),
        sa.Column('seq_no', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['job_no'], ['new_job.job_no'], ),
        sa.ForeignKeyConstraint(['sid'], ['new_message.sid'], ),
        sa.ForeignKeyConstraint(['user_id'], ['new_users.id'], ),
        sa.PrimaryKeyConstraint('sid')
    )
    op.create_table('forward_callback',
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('seq_no', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('update_count', sa.Integer(), nullable=False),
        sa.Column('message_context', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['job_no'], ['new_job.job_no'], ),
        sa.ForeignKeyConstraint(['user_id'], ['new_users.id'], ),
        sa.PrimaryKeyConstraint('job_no', 'seq_no')
    )
    op.create_table('new_job_leave',
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('error', sa.String(length=32), nullable=True),
        sa.Column('leave_type', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['job_no'], ['new_job.job_no'], ),
        sa.PrimaryKeyConstraint('job_no')
        )
    op.create_table('new_leave_records',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('sync_status', sa.String(length=10), nullable=True),
        sa.Column('leave_status', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['job_no'], ['new_job_leave.job_no'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('task_daemon',
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=True),
        sa.Column('user_id', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['job_no'], ['job_daemon.job_no'], ),
        sa.ForeignKeyConstraint(['user_id'], ['new_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('task_leave',
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('job_no', sa.String(length=32), nullable=False),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=True),
        sa.Column('user_id', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['job_no'], ['new_job_leave.job_no'], ),
        sa.ForeignKeyConstraint(['user_id'], ['new_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('task_leave')
    op.drop_table('task_daemon')
    op.drop_table('new_leave_records')
    op.drop_table('new_job_leave')
    op.drop_table('message_known')
    op.drop_table('job_daemon')
    op.drop_table('forward_callback')
    op.drop_table('sent_message_status')
    op.drop_table('new_job')
    op.drop_table('message_unknown')
    op.drop_table('lookups')
    op.drop_table('new_users')
    op.drop_table('new_message')

    # ### end Alembic commands ###
