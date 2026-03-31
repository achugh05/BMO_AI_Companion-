#Download canvasapi python wrapper to interact with Canvas api
#pip install canvasapi
from canvasapi import Canvas
from zoneinfo import ZoneInfo

#Canvas Domain
API_URL = 'https://canvas.ubc.ca'
# Canvas API key/token
API_KEY = '11224~CLBLaAYeUJVBTXaDefT8c9Q36eWxBBunUXmK9fkXCknXBGUnBy4YrcMxhJAVATue'
canvas = Canvas(API_URL, API_KEY)
user = canvas.get_current_user()
courses = user.get_courses(enrollment_state='active')
coursedict = {}
    
for course in courses:

    if hasattr(course, 'name'):
        #Take course code
        course_code = course.name[:10]
        clean_course_code = course_code.upper().replace("_O", "").replace(" ", "")
        coursedict[clean_course_code] = course


#Periods user can check for
periods = {
        'DAY',
        'TOMORROW',
        'WEEK'
    }

#Time zone
localtimezone = ZoneInfo("America/Vancouver")