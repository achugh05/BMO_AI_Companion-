from .canvas_setup import courses,localtimezone
from datetime import datetime, timedelta, timezone

#Takes input of days ahead and optional input of specific course
def get_assignments(days_ahead, course_list=courses):

    #Get current time and target time
    now = datetime.now(timezone.utc)
    future_date = now + timedelta(days=days_ahead)
    
    upcoming_tasks = []

    #For every enrolled course or specified course
    for course in course_list:

        #If course exist
        if not hasattr(course, 'name'):
            continue

        try:
            #Get all assignments in course
            assignments = course.get_assignments(bucket='upcoming')
            
            #Get due date for assignments in course
            for assignment in assignments:

                # Skip assignments without due dates
                if not hasattr(assignment, 'due_at') or assignment.due_at is None:
                    continue
                
                #Get due date in local timezone
                due_date = datetime.strptime(assignment.due_at, "%Y-%m-%dT%H:%M:%SZ")
                due_date = due_date.replace(tzinfo=timezone.utc)

                #Convert to local timezone
                local_due_date = due_date.astimezone(localtimezone)
                
                #If due date is within time period add to dictonary
                if now <= due_date <= future_date:
                    upcoming_tasks.append({
                        'course': " ".join(course.name.upper().replace(" ", "")),
                        'assignment': assignment.name,
                        'due_date': local_due_date.strftime("%B %d, %H %M")
                    })
        except Exception:
            continue

    #If there are assignments due
    if upcoming_tasks:
        # Sort due date by chronological order
        upcoming_tasks.sort(key=lambda x: x['due_date'])

        #Turn dictionary into string
        upcoming_tasks_str = "Assignments due within next " + str(days_ahead) + " days:\n"
        for task in upcoming_tasks:
            upcoming_tasks_str += f"{task['course']}: {task['assignment']} due on {task['due_date']}\n"

        return upcoming_tasks_str
    
    #No assignments due
    else:
        return "No assignments due within the next " + str(days_ahead) + " days.\n"
