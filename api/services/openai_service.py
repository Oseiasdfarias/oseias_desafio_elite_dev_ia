# backend/services/openai_service.py

import os
import time
import asyncio
import json
from openai import OpenAI
from typing import List, Dict, Any

# Importações relativas
from .pipefy_service import PipefyService
from .calendar_service import CalendarService, format_datetime_sao_paulo # Importa a função helper

# Importação do pacote pai
from models import Lead

# --- NOVO: Armazenamento temporário para mapear slots ---
# Em produção, isso deveria ser um cache (Redis) ou banco de dados
# Mapeia thread_id -> { "display_slot_1": slot_utc_1, "display_slot_2": slot_utc_2, ... }
temp_slot_mapping: Dict[str, Dict[str, Dict[str, str]]] = {}

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
        # (Este método permanece igual)
        max_wait_time = 180
        start_time = time.time()
        while True:
            if time.time() - start_time > max_wait_time:
                print(f"Run {run_id} timed out after {max_wait_time}s")
                raise TimeoutError("Run execution timeout")
            run = self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
            if run.status in ["queued", "in_progress"]:
                print(f"Run {run_id} status: {run.status}")
                await asyncio.sleep(1)
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
        """Lida com ações requeridas pelo assistente, gerenciando conversões de horário."""
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
                        # O assistente já deve enviar meeting_datetime em UTC ISO
                        lead_data = {
                            "name": arguments.get("nome"),
                            "email": arguments.get("email"),
                            "company": arguments.get("empresa"),
                            "need": arguments.get("necessidade"),
                            "interest_confirmed": arguments.get("interesse_confirmado", False),
                            "meeting_link": arguments.get("meeting_link"),
                            "meeting_datetime": arguments.get("meeting_datetime") # Esperado em UTC ISO
                        }
                        lead_data_clean = {k: v for k, v in lead_data.items() if v is not None}
                        lead = Lead(**lead_data_clean)
                        async with PipefyService() as pipefy_service:
                            output = await pipefy_service.create_or_update_lead(lead)
                        print(f"Lead registration result: {output}")

                    elif function_name == "oferecerHorarios":
                        calendar_service = CalendarService()
                        dias = arguments.get("dias", 7)
                        result = await calendar_service.get_available_slots(days=dias)

                        if result.get("success"):
                            # Guarda o mapeamento
                            temp_slot_mapping[thread_id] = {
                                display: utc for display, utc in zip(result["slots_display"], result["slots_utc"])
                            }
                            # Envia apenas os slots de exibição para o assistente
                            output = {"status": "success", "available_slots_display": result["slots_display"]}
                            print(f"Available slots (display): {result['slots_display']}")
                        else:
                            output = {"status": "error", "message": result.get("error", "Erro ao buscar horários.")}
                            print(f"Error fetching slots: {output['message']}")
                        
                        # Limpa mapeamento antigo se houver nova busca (para o mesmo thread)
                        if thread_id in temp_slot_mapping and not result.get("success"):
                            del temp_slot_mapping[thread_id]


                    elif function_name == "agendarReuniao":
                        # O assistente envia a *string de exibição* escolhida pelo usuário
                        chosen_display_slot_start = arguments.get("data_inicio_display") # Novo parâmetro esperado
                        lead_email = arguments["email_lead"]
                        lead_name = arguments.get("nome_lead", "Lead")

                        if not chosen_display_slot_start:
                            output = {"success": False, "error": "Parâmetro 'data_inicio_display' não fornecido pelo assistente."}
                        elif thread_id not in temp_slot_mapping or chosen_display_slot_start not in temp_slot_mapping[thread_id]:
                            output = {"success": False, "error": f"Horário escolhido ('{chosen_display_slot_start}') inválido ou não encontrado no mapeamento. Peça para o usuário escolher novamente da lista."}
                        else:
                            # Encontra o slot UTC correspondente
                            slot_utc = temp_slot_mapping[thread_id][chosen_display_slot_start]
                            start_time_utc_iso = slot_utc["start_time"]
                            end_time_utc_iso = slot_utc["end_time"]

                            print(f"--- [DEBUG] Mapeado '{chosen_display_slot_start}' para UTC: {start_time_utc_iso} ---")

                            calendar_service = CalendarService()
                            result = await calendar_service.schedule_meeting_from_assistant(
                                start_time_utc_iso, end_time_utc_iso, lead_email, lead_name
                            )

                            if result.get("success"):
                                # Converte o resultado UTC para exibição
                                confirmed_start_utc = result.get("start_time_utc")
                                display_time_sao_paulo = format_datetime_sao_paulo(confirmed_start_utc) if confirmed_start_utc else "Horário não confirmado"
                                
                                # Envia o resultado formatado para o assistente
                                output = {
                                    "success": True,
                                    "meeting_link": result.get("meeting_link"),
                                    "start_time_display": display_time_sao_paulo, # Hora para exibir
                                    "start_time_utc": confirmed_start_utc # Hora UTC para registrarLead
                                }
                                print(f"Meeting scheduled successfully. Display time: {display_time_sao_paulo}")
                                # Limpa o mapeamento após agendamento bem-sucedido
                                if thread_id in temp_slot_mapping:
                                    del temp_slot_mapping[thread_id]
                            else:
                                output = result # Retorna o erro
                                print(f"Error scheduling meeting: {output.get('error')}")
                    else:
                        output = {"error": f"Função {function_name} não reconhecida"}

                except Exception as e:
                    print(f"Error executing tool {function_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    output = {"error": f"Erro interno ao executar {function_name}: {e}"}

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
                run = await self._wait_for_run_completion(thread_id, run.id)
            return run

        except Exception as e:
            print(f"Critical error in _handle_required_action: {e}")
            import traceback
            traceback.print_exc()
            try:
                self.client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
            except Exception as cancel_e:
                print(f"Error cancelling run after critical error: {cancel_e}")
            return run


    async def get_assistant_response(self, thread_id: str, message: str) -> str:
        """Obtém resposta do assistente"""
        # (Este método permanece igual)
        print(f"Processing message in thread: {thread_id}")
        try:
            self.client.beta.threads.messages.create(thread_id=thread_id, role="user", content=message)
        except Exception as e:
            print(f"Error adding message to thread: {e}")
            return f"Erro ao processar sua mensagem: {e}"
        run = self.client.beta.threads.runs.create(thread_id=thread_id, assistant_id=self.assistant_id)
        print(f"Created run: {run.id} with status: {run.status}")
        try:
            run = await self._wait_for_run_completion(thread_id, run.id)
            while run.status == "requires_action":
                print("Run requires action, handling tool calls...")
                run = await self._handle_required_action(thread_id, run)
            if run.status == "completed":
                messages = self.client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)
                if messages.data and messages.data[0].content:
                    response = messages.data[0].content[0].text.value
                    print(f"Assistant response: {response}")
                    return response
                else:
                    # Limpa mapeamento se a resposta final for vazia (pouco provável)
                    if thread_id in temp_slot_mapping: del temp_slot_mapping[thread_id]
                    return "Não recebi uma resposta do assistente."
            else:
                error_msg = f"O assistente falhou (status final: {run.status})"
                if hasattr(run, 'last_error') and run.last_error: error_msg += f". Erro: {run.last_error.message}"
                print(error_msg)
                # Limpa mapeamento se o run falhar
                if thread_id in temp_slot_mapping: del temp_slot_mapping[thread_id]
                return error_msg
        except TimeoutError:
            print(f"Run {run.id} timed out.")
            # Limpa mapeamento em caso de timeout
            if thread_id in temp_slot_mapping: del temp_slot_mapping[thread_id]
            return "O assistente demorou muito para responder. Tente novamente."
        except Exception as e:
            print(f"Error during run processing: {e}")
            import traceback
            traceback.print_exc()
            # Limpa mapeamento em caso de erro geral
            if thread_id in temp_slot_mapping: del temp_slot_mapping[thread_id]
            return f"Ocorreu um erro inesperado: {e}"

    def cleanup_thread(self, thread_id: str):
        """Deleta um thread específico da OpenAI e limpa o mapeamento"""
        try:
            self.client.beta.threads.delete(thread_id)
            print(f"Thread {thread_id} deleted")
        except Exception as e:
            print(f"Error cleaning up thread {thread_id}: {e}")
        finally:
            # Garante que o mapeamento seja limpo mesmo se a deleção falhar
            if thread_id in temp_slot_mapping:
                del temp_slot_mapping[thread_id]
                print(f"Slot mapping for thread {thread_id} cleared.")

