from .canvas_setup import coursedict, user

# Takes target courses codes or defaults to all active courses
def get_current_grades(target_courses=None):
    
    # Check if a specific list of courses was requested
    if target_courses is None:
        target_courses = list(coursedict.keys())
        specific_request = False
    else:
        specific_request = True

    course_grades = {}

    for course_code in target_courses:
        
        # If the requested course is valid get enrollment
        if course_code in coursedict:
            course = coursedict[course_code]
            enrollments = course.get_enrollments(user_id=user.id)
            
            # Get grade from enrollment
            for enrollment in enrollments:
                if hasattr(enrollment, 'grades'):
                    score = enrollment.grades.get('current_score')
                    course_grades[course_code] = score
        else:
            # Course not found
            course_grades[course_code] = "Course not found"
    
    # Format the opening string based on the request type
    if specific_request:
        courses_requested = " ".join(", ".join(target_courses))
        course_grades_str = f"Your current grades for {courses_requested} are:\n"
    else:
        course_grades_str = 'Your current grades are:\n'

    # Put requested grades into a string
    for course_code, grade in course_grades.items():
        # Check specifically for None so we don't accidentally hide 0.0 scores
        if grade is not None:
            course_grades_str += f"{" ".join(course_code)}: {grade}\n"
    
    return course_grades_str