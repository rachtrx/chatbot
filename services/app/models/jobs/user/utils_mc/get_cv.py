from utilities import print_all_dates, print_relations_list
from constants import CONFIRM, CANCEL

######################################
# CV TEMPLATES FOR SINGLE MESSAGE
######################################

def get_confirm_mc_cv(relations_list, job):

    return {
        '1': job.user.name,
        '2': job._start_date,
        '3': job._end_date,
        '4': str(job.duration),
        '5': print_relations_list(relations_list),
        '6': str(CONFIRM),
        '7': str(CANCEL)
    }

def get_later_start_date_confirm_mc_cv(relations_list, job):

    return {
        '1': job.user.name,
        '2': job._start_date,
        '3': job._end_date,
        '4': str(job.duration),
        '5': print_relations_list(relations_list),
        '6': str(CONFIRM),
        '7': str(CANCEL)
    }

def get_overlap_confirm_mc_cv(relations_list, job):

    return {
        '1': job.user.name,
        '2': print_all_dates(job.duplicate_dates, date_obj=True),
        '3': print_all_dates(job.non_duplicate_dates, date_obj=True),
        '4': str(job.duration),
        '5': print_relations_list(relations_list),
        '6': str(CONFIRM),
        '7': str(CANCEL)
    }

def get_later_start_date_and_overlap_confirm_mc_cv(relations_list, job):
    
    return {
        '1': job.user.name,
        '2': print_all_dates(job.duplicate_dates, date_obj=True),
        '3': print_all_dates(job.non_duplicate_dates, date_obj=True),
        '4': str(job.duration),
        '5': print_relations_list(relations_list),
        '6': str(CONFIRM),
        '7': str(CANCEL)
    }