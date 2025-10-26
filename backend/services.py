import os
import time
import asyncio
from dotenv import load_dotenv
from openai import OpenAI
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json
import uuid

from models import Lead, Meeting, AvailableSlot

load_dotenv()

# OpenAI Service Corrigido
class OpenAIService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.assistant_id = os.getenv("OPENAI_ASSISTANT_ID")
        if not self.assistant_id:
            raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")

    def create_thread(self):
        """Cria um novo thread"""
        try:
            thread = self.client.beta.threads.create()
            print(f"Thread created: {thread.id}")
            return thread.id
        except Exception as e:
            print(f"Error creating thread: {e}")
            raise

    async def _wait_for_run_completion(self, thread_id: str, run_id: str):
        """Aguarda a conclusão de um run com timeout"""
        max_wait_time = 180  # 3 minutos máximo
        start_time = time.time()
        
        while True:
            if time.time() - start_time > max_wait_time:
                print(f"Run {run_id} timed out after {max_wait_time}s")
                raise TimeoutError("Run execution timeout")
                
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id
            )
            
            if run.status in ["queued", "in_progress"]:
                print(f"Run {run_id} status: {run.status}")
                await asyncio.sleep(1) # Polling de 1 segundo
            elif run.status in ["completed", "failed", "cancelled", "expired"]:
                print(f"Run {run_id} finished with status: {run.status}")
                return run
            elif run.status == "requires_action":
                print(f"Run {run_id} requires action.")
                return run
            else:
                print(f"Run {run_id} unknown status: {run.status}")
                raise Exception(f"Unknown run status: {run.status}")

    async def _handle_required_action(self, thread_id: str, run):
        """Lida com ações requeridas pelo assistente"""
        try:
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs = []

            print(f"Processing {len(tool_calls)} tool calls...")

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                output = None

                print(f"Executing tool: {function_name}")
                print(f"Arguments: {arguments}")

                try:
                    if function_name == "registrarLead":
                        # Mapear argumentos (agora padronizados em português)
                        lead_data = {
                            "name": arguments.get("nome"),
                            "email": arguments.get("email"),
                            "company": arguments.get("empresa"),
                            "need": arguments.get("necessidade"),
                            "interest_confirmed": arguments.get("interesse_confirmado", False),
                            "meeting_link": arguments.get("meeting_link"),
                            "meeting_datetime": arguments.get("meeting_datetime")
                        }
                        
                        # Remover chaves None para o Pydantic usar os defaults
                        lead_data_clean = {k: v for k, v in lead_data.items() if v is not None}
                        
                        lead = Lead(**lead_data_clean)
                        
                        async with PipefyService() as pipefy_service:
                            output = await pipefy_service.create_or_update_lead(lead)
                        
                        print(f"Lead registration result: {output}")

                    elif function_name == "oferecerHorarios":
                        calendar_service = CalendarService()
                        dias = arguments.get("dias", 7)
                        output_slots = await calendar_service.get_available_slots(days=dias)
                        # Retorna uma lista simples para o LLM, ou uma mensagem de erro
                        if not output_slots:
                             output = {"status": "error", "message": "Não há horários disponíveis nos próximos dias."}
                        else:
                            output = {"status": "success", "available_slots": output_slots}
                        
                        print(f"Available slots: {len(output_slots)} encontrados")

                    elif function_name == "agendarReuniao":
                        calendar_service = CalendarService()
                        # Usa os nomes de parâmetros em português
                        output = await calendar_service.schedule_meeting_from_assistant(arguments)
                        print(f"Meeting scheduled: {output}")

                    else:
                        output = {"error": f"Função {function_name} não reconhecida"}

                except Exception as e:
                    print(f"Error executing tool {function_name}: {e}")
                    output = {"error": str(e)}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(output, default=str)
                })

            if tool_outputs:
                print(f"Submitting {len(tool_outputs)} tool outputs...")
                run = self.client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )
                
                print("Waiting for completion after tool submission...")
                # Aguardar a conclusão após submeter as tool outputs
                run = await self._wait_for_run_completion(thread_id, run.id)
            
            return run

        except Exception as e:
            print(f"Critical error in _handle_required_action: {e}")
            # Tentar cancelar o run se algo crítico falhar aqui
            try:
                self.client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
            except Exception as cancel_e:
                print(f"Error cancelling run after critical error: {cancel_e}")
            return run

    async def get_assistant_response(self, thread_id: str, message: str) -> str:
        """Obtém resposta do assistente"""
        
        print(f"Processing message in thread: {thread_id}")

        # Adicionar mensagem do usuário ao thread
        try:
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
        except Exception as e:
            print(f"Error adding message to thread: {e}")
            return f"Erro ao processar sua mensagem: {e}"

        # Criar novo run
        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=self.assistant_id
        )

        print(f"Created run: {run.id} with status: {run.status}")

        try:
            # Aguardar conclusão inicial
            run = await self._wait_for_run_completion(thread_id, run.id)

            # Loop para lidar com MÚLTIPLAS chamadas de função sequenciais
            while run.status == "requires_action":
                print("Run requires action, handling tool calls...")
                run = await self._handle_required_action(thread_id, run)
                # _handle_required_action já espera o próximo status (que pode ser
                # 'completed' ou 'requires_action' de novo), então o loop reavalia.

            # Obter resposta final
            if run.status == "completed":
                messages = self.client.beta.threads.messages.list(
                    thread_id=thread_id,
                    order="desc",
                    limit=1
                )
                if messages.data and messages.data[0].content:
                    response = messages.data[0].content[0].text.value
                    print(f"Assistant response: {response}")
                    return response
                else:
                    return "Não recebi uma resposta do assistente."
            else:
                # Se saiu do loop, mas não foi 'completed' (ex: failed, cancelled)
                error_msg = f"O assistente falhou (status final: {run.status})"
                if hasattr(run, 'last_error') and run.last_error:
                    error_msg += f". Erro: {run.last_error.message}"
                print(error_msg)
                return error_msg
        
        except TimeoutError:
            print(f"Run {run.id} timed out.")
            return "O assistente demorou muito para responder. Tente novamente."
        except Exception as e:
            print(f"Error during run processing: {e}")
            return f"Ocorreu um erro inesperado: {e}"

    def cleanup_thread(self, thread_id: str):
        """Deleta um thread específico da OpenAI"""
        try:
            self.client.beta.threads.delete(thread_id)
            print(f"Thread {thread_id} deleted")
        except Exception as e:
            print(f"Error cleaning up thread {thread_id}: {e}")


# Pipefy Service com HTTPX Assíncrono e IDs por .env
class PipefyService:
    """
    Serviço para integração com a API da Pipefy
    Gerencia criação e atualização de cards no pipe de leads
    """
    
    def __init__(self):
        self.api_key = os.getenv("PIPEFY_API_KEY")
        self.pipe_id = os.getenv("PIPEFY_PIPE_ID")
        self.api_url = "https://api.pipefy.com/graphql"

        # Carrega IDs de campos do .env
        self.field_id_name = os.getenv("PIPEFY_NAME_FIELD_ID", "nome_do_lead")
        self.field_id_email = os.getenv("PIPEFY_EMAIL_FIELD_ID", "e_mail")
        self.field_id_company = os.getenv("PIPEFY_COMPANY_FIELD_ID", "empresa")
        self.field_id_need = os.getenv("PIPEFY_NEED_FIELD_ID", "necessidade_espec_fica")
        self.field_id_interest = os.getenv("PIPEFY_INTEREST_FIELD_ID", "checklist_vertical")
        self.field_id_meeting_link = os.getenv("PIPEFY_MEETING_LINK_FIELD_ID", "link_da_reuni_o")
        self.field_id_meeting_time = os.getenv("PIPEFY_MEETING_TIME_FIELD_ID", "data_e_hora_da_reuni_o")
        
        # Nome do campo de email (para busca)
        self.email_field_name = os.getenv("PIPEFY_EMAIL_FIELD_NAME", "E-mail")

        if not all([self.api_key, self.pipe_id, self.field_id_email]):
            raise ValueError("Pipefy environment variables are not properly configured (PIPEFY_API_KEY, PIPEFY_PIPE_ID, PIPEFY_EMAIL_FIELD_ID)")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _execute_query(self, query: str) -> Dict[str, Any]:
        """Executa uma query GraphQL na API da Pipefy de forma assíncrona"""
        try:
            response = await self.client.post(
                self.api_url, 
                headers=self.headers, 
                json={"query": query}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Pipefy API HTTP error: {e.response.status_code} - {e.response.text}")
            return {"errors": [{"message": f"HTTP error: {e.response.status_code}"}]}
        except httpx.RequestError as e:
            print(f"Pipefy API request error: {e}")
            return {"errors": [{"message": f"Request error: {str(e)}"}]}
        except Exception as e:
            print(f"Pipefy API unexpected error: {e}")
            return {"errors": [{"message": str(e)}]}

    async def _find_card_by_email(self, email: str) -> Dict[str, Any]:
        """Encontra cards existentes pelo email"""
        # Esta query busca os últimos 50 cards. Para produção, considere uma busca mais robusta.
        query = f'''
        {{
            cards(pipe_id: {self.pipe_id}, first: 50) {{
                edges {{
                node {{
                    id
                    title
                    fields {{
                    name
                    value
                    }}
                }}
                }}
            }}
        }}
        '''
        
        result = await self._execute_query(query)
        
        if result.get('errors'):
            return result
            
        cards_found = []
        edges = result.get('data', {}).get('cards', {}).get('edges', [])
        
        for edge in edges:
            card = edge['node']
            for field in card.get('fields', []):
                # Usa a variável de ambiente para o NOME do campo
                if field.get('name') == self.email_field_name and field.get('value') == email:
                    cards_found.append(card)
                    break
        
        return {
            'data': {
                'cards': {
                    'edges': [{'node': card} for card in cards_found]
                }
            }
        }
    
    # ADICIONE ESTA FUNÇÃO DENTRO DA CLASSE PipefyService
    async def _update_card_field(self, card_id: str, field_id: str, value: Any) -> Dict[str, Any]:
        """Atualiza um campo individual de um card"""
        
        # Usa a mesma formatação de valor
        formatted_value = self._format_field_value(value)
        
        mutation = f'''
        mutation {{
            updateCardField(input: {{
                card_id: "{card_id}",
                field_id: "{field_id}",
                new_value: {formatted_value}
            }}) {{
                card {{
                id
                title
                }}
                success
            }}
        }}
        '''
        
        return await self._execute_query(mutation)

    def _format_field_value(self, value):
        """Escapa aspas e caracteres especiais para a query GraphQL"""
        if isinstance(value, str):
            return json.dumps(value) # json.dumps lida com aspas, \n, etc.
        if isinstance(value, bool):
            return '"Confirmado"' if value else '"Não confirmado"'
        if isinstance(value, datetime):
            return f'"{value.isoformat()}"'
        if value is None:
            return None
        return f'"{str(value)}"'


    async def _create_card(self, lead: Lead) -> Dict[str, Any]:
        """Cria um novo card no pipe"""
        
        fields_map = {
            self.field_id_name: lead.name or "Lead (Nome Pendente)",
            self.field_id_email: lead.email,
            self.field_id_company: lead.company or "Empresa não informada",
            self.field_id_need: lead.need or "Interesse em nossos serviços",
            self.field_id_interest: "Confirmado" if lead.interest_confirmed else "Não confirmado",
            self.field_id_meeting_link: lead.meeting_link,
            self.field_id_meeting_time: lead.meeting_datetime.isoformat() if lead.meeting_datetime else None
        }

        fields_array = []
        for field_id, value in fields_map.items():
            if value is not None:
                formatted_value = self._format_field_value(value)
                fields_array.append(f'{{field_id: "{field_id}", field_value: {formatted_value}}}')

        fields_str = ", ".join(fields_array)
        
        mutation = f'''
        mutation {{
            createCard(input: {{
                pipe_id: {self.pipe_id},
                title: "{lead.name or 'Novo Lead'} - {lead.email}",
                fields_attributes: [
                {fields_str}
                ]
            }}) {{
                card {{
                id
                title
                }}
            }}
        }}
        '''
        
        print(f"Pipefy Create Mutation: {mutation}")
        result = await self._execute_query(mutation)
        print(f"Pipefy Create Response: {result}")
        return result

    async def _update_card_fields(self, card_id: str, lead: Lead) -> Dict[str, Any]:
        """Atualiza todos os campos de um card existente (um por um, em paralelo)"""
        
        # Mapeia os campos do Pydantic para os IDs de campo do Pipefy
        field_mapping = {
            self.field_id_name: lead.name,
            self.field_id_email: lead.email,
            self.field_id_company: lead.company,
            self.field_id_need: lead.need,
            self.field_id_interest: "Confirmado" if lead.interest_confirmed else "Não confirmado",
            self.field_id_meeting_link: lead.meeting_link,
            self.field_id_meeting_time: lead.meeting_datetime.isoformat() if lead.meeting_datetime else None
        }
        
        successful_updates = []
        failed_updates = []
        
        tasks = []
        for field_id, value in field_mapping.items():
            if value is not None:
                # Cria uma tarefa para cada atualização de campo
                tasks.append(self._update_card_field(card_id, field_id, value))
        
        # Executa todas as atualizações em paralelo
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Coleta os resultados
        field_ids = [fid for fid, val in field_mapping.items() if val is not None]
        for i, result in enumerate(results):
            field_id = field_ids[i]
            if isinstance(result, Exception):
                print(f"Error updating field {field_id}: {result}")
                failed_updates.append(field_id)
            elif result.get('data', {}).get('updateCardField', {}).get('success'):
                successful_updates.append(field_id)
            else:
                print(f"Failed to update field {field_id}: {result.get('errors')}")
                failed_updates.append(field_id)
        
        if successful_updates:
            return {
                'success': True,
                'message': f'Successfully updated {len(successful_updates)} fields',
                'card_id': card_id,
                'successful_updates': successful_updates,
                'failed_updates': failed_updates
            }
        else:
            return {
                'success': False,
                'message': 'All field updates failed',
                'card_id': card_id,
                'errors': [str(e) for e in results if isinstance(e, Exception)]
            }

    async def create_or_update_lead(self, lead: Lead) -> Dict[str, Any]:
        """
        Cria ou atualiza um lead no Pipefy
        """
        try:
            if not lead.email:
                return {"success": False, "error": "Email is required to create or update a lead"}

            existing_card_data = await self._find_card_by_email(lead.email)
            
            if existing_card_data.get('errors'):
                return {"success": False, "error": "Search failed", "details": existing_card_data['errors']}
            
            cards_edges = existing_card_data.get("data", {}).get("cards", {}).get("edges", [])
            
            if cards_edges:
                card_id = cards_edges[0]["node"]["id"]
                print(f"Found existing card {card_id} for email {lead.email}. Updating...")
                return await self._update_card_fields(card_id, lead)
            else:
                print(f"No card found for email {lead.email}. Creating new card...")
                result = await self._create_card(lead)
                if result.get('data', {}).get('createCard'):
                    return {
                        'success': True,
                        'message': 'Card created successfully',
                        'card_id': result['data']['createCard']['card']['id']
                    }
                else:
                    return {
                        'success': False,
                        'message': 'Failed to create card',
                        'errors': result.get('errors', [])
                    }
        except Exception as e:
            print(f"Error in create_or_update_lead: {e}")
            return {"success": False, "error": str(e)}

    async def close(self):
        """Fecha o client HTTP"""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

# Calendar Service (Atualizado para corresponder aos nomes de parâmetros em português)
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