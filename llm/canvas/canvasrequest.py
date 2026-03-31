import re
from .canvas_setup import periods, coursedict
from .assignmentfunctions import get_assignments
from .gradesfunction import get_current_grades

def canvasFunction(string_inp):

    #Identify user request type
    user_request = string_inp.upper().replace(" ", "")
    request_type = typeOfRequest(user_request)
    
    target_course_codes = []
    target_course_objects = []
    
    #Check if course code is mentioned
    for code, course_obj in coursedict.items():
        if code in user_request:
            target_course_codes.append(code)
            target_course_objects.append(course_obj)
            
    # Default to all courses
    if not target_course_codes:
        target_course_codes = list(coursedict.keys())
        target_course_objects = list(coursedict.values())
    
    
    if request_type == 'ASSIGNMENT':
        days_ahead = 7

        #See if a number is mentioned prior to day or week
        day_match = re.search(r'(\d+)DAY', user_request)
        week_match = re.search(r'(\d+)WEEK', user_request)

        if day_match:
            days_ahead = int(day_match.group(1))
        elif week_match:
            days_ahead = int(week_match.group(1)) * 7
        else:
            matched_period = None
            for period in periods:
                clean_period = period.upper().replace(" ", "")
                if clean_period in user_request:
                    matched_period = clean_period
                    break

            #Check matched period and set days ahead
            if matched_period == 'TODAY' or matched_period == 'DAY':
                days_ahead = 1
            elif matched_period == 'TOMORROW':
                days_ahead = 2
            elif matched_period == 'THISWEEK' or matched_period == 'WEEK':
                days_ahead = 7
            elif matched_period == 'NEXTWEEK':
                days_ahead = 14
        
        return get_assignments(days_ahead, target_course_objects)

    elif request_type == 'GRADE':
        return get_current_grades(target_course_codes)

    # If request is unknown
    return "Invalid request"


def typeOfRequest(user_req):

    # Request type keywords
    categories = {
        'ASSIGNMENT': ['HANDIN', 'DUE', 'DEADLINE', 'WHENIS', 'SUBMIT', 'EXTENSION', 'TIMELINE','ASSIGNMENT', 'HOMEWORK','FINISH'],
        'GRADE': ['GRADE', 'SCORE', 'MARK', 'DIDIPASS','RESULT', 'FEEDBACK']
    }

    # Find matching type
    for category, keywords in categories.items():
        if any(keyword in user_req for keyword in keywords):
            return category
            
    # Nothing matches
    return None