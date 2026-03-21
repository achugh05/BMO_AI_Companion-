from canvas_setup import courses,localtimezone
from datetime import datetime, timedelta, timezone

def get_all_assignments(days_ahead):

    #Get current time and target time
    now = datetime.now(timezone.utc)
    future_date = now + timedelta(days=days_ahead)
    
    upcoming_tasks = []
    
    #For enrolled courses check upcoming assignments and take the due dates
    for course in courses:
        
        if not hasattr(course, 'name'):
            continue

        try:
            assignments = course.get_assignments(bucket='upcoming')
            
            #Get all upcoming assignments
            for assignment in assignments:
                # Skip assignments without due dates
                if not hasattr(assignment, 'due_at') or assignment.due_at is None:
                    continue
                
                #Get due date of individual assignment
                due_date = datetime.strptime(assignment.due_at, "%Y-%m-%dT%H:%M:%SZ")
                due_date = due_date.replace(tzinfo=timezone.utc)

                #Convert to local timezone
                local_due_date = due_date.astimezone(localtimezone)
                
                #If due date is within time period add to list
                if now <= due_date <= future_date:
                    upcoming_tasks.append({
                        'course': course.name[:8],
                        'assignment': assignment.name,
                        'due_date': local_due_date.strftime("%Y-%m-%d %H:%M")
                    })
        except Exception:
            continue

    # Sort the final list chronologically
    upcoming_tasks.sort(key=lambda x: x['due_date'])
    return upcoming_tasks