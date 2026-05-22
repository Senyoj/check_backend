from datetime import datetime, date
from pydantic import BaseModel, Field, field_validator

class ExtractedCourse(BaseModel):
    course_name: str
    day_of_week: str
    time_start: str
    time_end: str
    location: str
    notification_lead_minutes: int | None = 30

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
    semester_end_date: str | None = None
    schedule: list[ExtractedCourse]

class CourseNotificationSettings(BaseModel):
    course_name: str
    notification_lead_minutes: int = Field(default=30, ge=0, le=1440)

class TimetableSetupRequest(BaseModel):
    semester_end_date: date
    fcm_token: str | None = None
    course_notifications: list[CourseNotificationSettings] | None = None

    @field_validator("semester_end_date")
    @classmethod
    def validate_end_date(cls, end_date: date) -> date:
        if end_date < date.today():
            raise ValueError("semester_end_date must be in the future")
        return end_date

