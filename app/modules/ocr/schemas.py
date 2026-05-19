from datetime import datetime
from pydantic import BaseModel

class ExtractedCourse(BaseModel):
    course_name: str
    day_of_week: str
    time_start: str
    time_end: str
    location: str

class TimetableResponse(BaseModel):
    timetable_id: str
    extracted_at: datetime
    schedule: list[ExtractedCourse]

class SaveTimetableRequest(BaseModel):
    schedule: list[ExtractedCourse]

class ShareCreateResponse(BaseModel):
    share_code: str
    message: str = "Share created successfully."

class SharedTimetableResponse(BaseModel):
    share_code: str
    owner_id: str
    timetable_id: str
    shared_at: datetime
    saved_at: datetime
    schedule: list[ExtractedCourse]
