import os
import time
import asyncio
import json
from openai import OpenAI
from typing import List, Dict, Any

# Importações relativas para o mesmo pacote (services)
from .pipefy_service import PipefyService
from .calendar_service import CalendarService

# Importação relativa para o pacote pai (backend)
from models import Lead

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
                        
                        # Usa o PipefyService importado
                        async with PipefyService() as pipefy_service:
                            output = await pipefy_service.create_or_update_lead(lead)
                        
                        print(f"Lead registration result: {output}")

                    elif function_name == "oferecerHorarios":
                        # Usa o CalendarService importado
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
                        # Usa o CalendarService importado
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