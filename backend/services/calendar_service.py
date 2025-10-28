# backend/services/calendar_service.py

import os
import asyncio
import httpx
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple
from dateutil.parser import parse as parse_datetime
from dateutil import tz
import locale

# Importação do módulo 'models'
from models import Lead, Meeting, AvailableSlot

# --- FUNÇÃO HELPER ATUALIZADA ---
def format_datetime_sao_paulo(dt_utc_iso: str) -> str:
    """Converte uma string ISO 8601 UTC para um formato legível em São Paulo (pt-BR)."""
    original_locale = None # Variável para guardar o locale original
    try:
        # Tenta definir o locale para pt_BR.UTF-8 para formatar o mês
        # Guarda o locale original para restaurá-lo depois
        try:
            original_locale = locale.getlocale(locale.LC_TIME) # Tenta pegar o atual (mais seguro)
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
        except locale.Error:
            print("Aviso: Locale 'pt_BR.UTF-8' não encontrado ou não suportado. O mês pode aparecer em inglês.")
            original_locale = None # Reseta se falhar

        dt_utc = parse_datetime(dt_utc_iso)
        sao_paulo_tz = tz.gettz("America/Sao_Paulo")
        dt_sao_paulo = dt_utc.astimezone(sao_paulo_tz)
        # Formato: "Dia de Mês(pt-BR) às HH:MM" (ex: "28 de Outubro às 12:00")
        formatted_string = dt_sao_paulo.strftime("%d de %B às %H:%M")
        return formatted_string

    except Exception as e:
        print(f"Erro ao formatar data {dt_utc_iso}: {e}")
        return dt_utc_iso # Retorna original em caso de erro
    finally:
        # Garante que o locale original seja restaurado
        if original_locale:
            try:
                locale.setlocale(locale.LC_TIME, original_locale)
            except locale.Error:
                pass # Ignora se não conseguir restaurar
# --- FIM DA FUNÇÃO ATUALIZADA ---

class CalendarService:
    def __init__(self):
        """
        Inicializa o serviço de calendário com as credenciais do Cal.com
        (Removida a dependência do CAL_COM_USER_ID)
        """
        self.api_key = os.getenv("CAL_COM_API_KEY")
        self.username = os.getenv("CAL_COM_USERNAME")
        self.api_url = "https://api.cal.com/v1"
        self.user_timezone = "America/Sao_Paulo" # Mantemos para a API

        event_type_id_str = os.getenv("CAL_COM_EVENT_TYPE_ID")
        duration_str = os.getenv("CAL_COM_EVENT_DURATION_MINUTES", "30")

        if not all([self.api_key, event_type_id_str, self.username]):
            raise ValueError("CAL_COM_API_KEY, CAL_COM_EVENT_TYPE_ID, e CAL_COM_USERNAME devem ser definidos no .env")

        try:
            self.event_type_id = int(event_type_id_str)
            self.event_duration_minutes = int(duration_str)
        except (ValueError, TypeError):
            raise ValueError("CAL_COM_EVENT_TYPE_ID e CAL_COM_EVENT_DURATION_MINUTES devem ser números válidos no .env")

    async def get_available_slots(self, days: int = 7) -> Dict[str, Any]:
        """
        Busca horários disponíveis (UTC) e retorna ambos os formatos:
        {
            "success": True,
            "slots_utc": [{"start_time": "ISO_UTC", "end_time": "ISO_UTC"}, ...],
            "slots_display": ["Legível SP 1", "Legível SP 2", ...]
        }
        ou {"success": False, "error": "..."}
        """
        print("--- [DEBUG] Iniciando get_available_slots ---")
        sao_paulo_tz = tz.gettz(self.user_timezone)
        now_in_tz = datetime.now(tz=sao_paulo_tz)
        start_date = now_in_tz.isoformat()
        end_date = (now_in_tz + timedelta(days=days)).isoformat()

        params = {
            "username": self.username,
            "eventTypeId": self.event_type_id,
            "dateFrom": start_date,
            "dateTo": end_date,
            "apiKey": self.api_key,
            "timezone": self.user_timezone
        }
        print(f"--- [DEBUG] Parâmetros da API Availability: {params} ---")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/availability", params=params)
                print(f"--- [DEBUG] Resposta da API Availability Status: {response.status_code} ---")
                response.raise_for_status()

            print(f"--- [DEBUG] Texto Bruto da Resposta Availability: {response.text[:200]}... ---")
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"--- [DEBUG] FALHA Availability: Resposta não é um JSON válido. Erro: {e} ---")
                return {"success": False, "error": "Resposta inválida da API Cal.com"}

            print("--- [DEBUG] JSON Availability parseado. Analisando slots... ---")
            slots_utc = []
            slots_display = []
            duration = timedelta(minutes=self.event_duration_minutes)
            now_utc = datetime.now(timezone.utc)
            busy_times = []
            for busy in data.get("busy", []):
                busy_times.append((parse_datetime(busy["start"]), parse_datetime(busy["end"])))

            for date_range in data.get("dateRanges", []):
                current_slot_start = parse_datetime(date_range["start"])
                range_end = parse_datetime(date_range["end"])

                while current_slot_start + duration <= range_end:
                    slot_end = current_slot_start + duration
                    if current_slot_start < now_utc:
                        current_slot_start += duration
                        continue
                    is_busy = False
                    for busy_start, busy_end in busy_times:
                        if current_slot_start < busy_end and slot_end > busy_start:
                            is_busy = True
                            break
                    if not is_busy:
                        start_iso = current_slot_start.isoformat()
                        end_iso = slot_end.isoformat()
                        slots_utc.append({"start_time": start_iso, "end_time": end_iso})
                        # Gera a string de exibição convertida
                        slots_display.append(format_datetime_sao_paulo(start_iso))

                        if len(slots_utc) >= 5: break # Limita a 5
                    current_slot_start += duration
                if len(slots_utc) >= 5: break

            print(f"--- [DEBUG] Slots encontrados: {len(slots_utc)} ---")
            # Retorna ambos os formatos
            return {"success": True, "slots_utc": slots_utc, "slots_display": slots_display}

        except httpx.RequestError as e:
            print(f"--- [DEBUG] FALHA DE REDE Availability (httpx): Erro: {e} ---")
            return {"success": False, "error": f"Erro de rede ao buscar horários: {e}"}
        except httpx.HTTPStatusError as e:
            print(f"--- [DEBUG] FALHA DE API Availability (Cal.com): {e.response.status_code} - {e.response.text} ---")
            return {"success": False, "error": f"Erro na API Cal.com (Availability): {e.response.text}"}
        except Exception as e:
            print(f"--- [DEBUG] FALHA INESPERADA Availability (Python): Erro: {e} ---")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"Erro interno ao processar horários: {e}"}

    async def schedule_meeting_from_assistant(self, start_time_utc_iso: str, end_time_utc_iso: str, lead_email: str, lead_name: str) -> Dict[str, Any]:
        """
        Agenda (cria um "booking") via API do Cal.com usando os horários UTC ISO.
        Retorna sucesso/falha, link e horários confirmados (em UTC ISO).
        (Removida a lógica de esperar e buscar - não é mais necessária)
        """
        print("--- [DEBUG] Iniciando schedule_meeting_from_assistant ---")
        try:
            payload = {
                "eventTypeId": self.event_type_id,
                "start": start_time_utc_iso,
                "end": end_time_utc_iso,
                "responses": {"email": lead_email, "name": lead_name},
                "status": "ACCEPTED",
                "timeZone": self.user_timezone,
                "language": "pt-BR",
                "metadata": {}
                # userId não é mais enviado
            }
            params = {"apiKey": self.api_key}

            print(f"--- [DEBUG] Payload da API Booking: {json.dumps(payload, indent=2)} ---")
            print(f"--- [DEBUG] Parâmetros da API Booking: {params} ---")

            async with httpx.AsyncClient() as client:
                post_response = await client.post(f"{self.api_url}/bookings", json=payload, params=params)
                print(f"--- [DEBUG] Resposta POST do Booking Status: {post_response.status_code} ---")
                post_response.raise_for_status()

            try:
                data = post_response.json()
                print(f"--- [DEBUG] Resposta JSON BRUTA do POST Booking: {json.dumps(data, indent=2)} ---")
                booking_id = data.get("id")
                booking_uid = data.get("uid")
                if not booking_id:
                    print("--- [DEBUG] FALHA Booking: Nenhum ID de agendamento na resposta POST. ---")
                    return {"success": False, "error": "Falha ao obter ID de agendamento do Cal.com"}
            except json.JSONDecodeError:
                print(f"--- [DEBUG] FALHA Booking: Resposta POST não é JSON. Texto: {post_response.text[:500]}... ---")
                return {"success": False, "error": "Resposta inválida após criação do agendamento"}

            # Extração do link (simplificada)
            meeting_link = data.get("videoCallUrl")
            print(f"--- [DEBUG] Tentativa 1 (videoCallUrl): {meeting_link} ---")
            if not meeting_link:
                location = data.get("location")
                print(f"--- [DEBUG] Tentativa 2 (location): {location} ---")
                if location and ("meet.google.com" in location or "zoom.us" in location):
                    meeting_link = location
            if not meeting_link:
                meeting_link = f"https://cal.com/booking/{booking_uid or booking_id}"
                print(f"--- [DEBUG] Fallback: Usando link de confirmação: {meeting_link} ---")

            return {
                "success": True,
                "meeting_link": meeting_link,
                "start_time_utc": data.get("startTime"), # Retorna UTC
                "end_time_utc": data.get("endTime"),     # Retorna UTC
                "message": "Reunião agendada com sucesso via Cal.com."
            }

        except httpx.RequestError as e:
            print(f"--- [DEBUG] FALHA DE REDE Booking (httpx): Erro: {e} ---")
            return {"success": False, "error": f"Erro de rede ao agendar: {e}"}
        except httpx.HTTPStatusError as e:
            print(f"--- [DEBUG] FALHA DE API Booking (Cal.com): {e.response.status_code} - {e.response.text} ---")
            return {"success": False, "error": f"Erro na API Cal.com: {e.response.text}"}
        except Exception as e:
            print(f"--- [DEBUG] FALHA INESPERADA Booking (Python): Erro: {e} ---")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"Erro interno ao agendar: {e}"}