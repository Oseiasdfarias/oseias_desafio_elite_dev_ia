import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json
import uuid


from models import Lead, Meeting, AvailableSlot

class CalendarService:
    def __init__(self):
        self.calendar_file = "calendar.json"
        self._ensure_calendar_file()

    def _ensure_calendar_file(self):
        """Garante que o arquivo de calendário existe"""
        if not os.path.exists(self.calendar_file):
            with open(self.calendar_file, "w") as f:
                json.dump([], f)

    async def get_available_slots(self, days: int = 7) -> List[Dict[str, str]]:
        """Retorna horários disponíveis para os próximos dias"""
        try:
            await asyncio.sleep(0.1)
            
            with open(self.calendar_file, "r") as f:
                booked_slots = json.load(f)

            now = datetime.now()
            available_slots = []
            
            for i in range(days):
                day = now + timedelta(days=i)
                if day.weekday() >= 5: # Pular fim de semana
                    continue
                    
                for hour in range(9, 18): # Horário comercial
                    slot_start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                    slot_end = slot_start + timedelta(hours=1)

                    if slot_start < now: # Ignora horários no passado
                        continue

                    is_booked = False
                    for booked_slot in booked_slots:
                        booked_start = datetime.fromisoformat(booked_slot["start_time"])
                        booked_end = datetime.fromisoformat(booked_slot["end_time"])
                        if slot_start < booked_end and slot_end > booked_start:
                            is_booked = True
                            break
                    
                    if not is_booked:
                        available_slots.append({
                            "start_time": slot_start.isoformat(), 
                            "end_time": slot_end.isoformat()
                        })
            
            # Limita a 5 para não sobrecarregar o LLM
            return available_slots[:5] 
        
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return []

    async def schedule_meeting(self, slot: AvailableSlot, lead: Lead) -> Dict[str, Any]:
        """Agenda uma reunião no calendário"""
        try:
            await asyncio.sleep(0.1)
            
            with open(self.calendar_file, "r+") as f:
                booked_slots = json.load(f)
                new_meeting = {
                    "start_time": slot.start_time.isoformat(),
                    "end_time": slot.end_time.isoformat(),
                    "lead_email": lead.email,
                    "lead_name": lead.name,
                    "company": lead.company,
                    "scheduled_at": datetime.now().isoformat()
                }
                booked_slots.append(new_meeting)
                f.seek(0)
                json.dump(booked_slots, f, indent=4)
                f.truncate()

            meeting_link = f"https://meet.google.com/{uuid.uuid4().hex[:10]}"
            
            meeting = Meeting(
                start_time=slot.start_time, 
                end_time=slot.end_time, 
                link=meeting_link
            )
            
            return {
                "success": True,
                "meeting_link": meeting.link,
                "start_time": meeting.start_time.isoformat(),
                "end_time": meeting.end_time.isoformat(),
                "message": "Meeting scheduled successfully"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def schedule_meeting_from_assistant(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Agenda reunião a partir dos argumentos do assistente (em português)"""
        try:
            start_time = datetime.fromisoformat(arguments["data_inicio"])
            end_time = datetime.fromisoformat(arguments["data_fim"])
            lead_email = arguments["email_lead"]
            
            lead = Lead(
                email=lead_email, 
                name=arguments.get("nome_lead", "Lead"),
                interest_confirmed=True
            )
            
            slot = AvailableSlot(start_time=start_time, end_time=end_time)
            return await self.schedule_meeting(slot, lead)
            
        except Exception as e:
            return {"success": False, "error": f"Invalid arguments: {e}"}