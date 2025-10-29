from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

class Lead(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = "Empresa não informada"
    need: Optional[str] = "Interesse em nossos serviços"
    interest_confirmed: bool = False
    meeting_link: Optional[str] = None
    meeting_datetime: Optional[datetime] = None

class Meeting(BaseModel):
    start_time: datetime
    end_time: datetime
    link: str

class AvailableSlot(BaseModel):
    start_time: datetime
    end_time: datetime

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    response: str
    lead_data: Optional[Lead] = None
    session_id: str
    thread_id: str
