# api/index.py

from fastapi import FastAPI, HTTPException, Depends # <-- Adiciona Depends
from fastapi.middleware.cors import CORSMiddleware # Mantido para Docker local
from typing import Dict, Annotated # <-- Adiciona Annotated
from dotenv import load_dotenv
import uuid
import logging
import os
import redis.asyncio as redis
import asyncio # <-- Adiciona asyncio para o health check

load_dotenv()

# Usa importações absolutas relativas a 'api/'
try:
    from api.models import ChatRequest, ChatResponse
    from api.services import OpenAIService
except ImportError:
    # Fallback para dev local (rodando de dentro da pasta backend/)
    from models import ChatRequest, ChatResponse
    from services import OpenAIService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- Configuração do Cliente Redis ---
# Mantém a URL global para fácil acesso
redis_url = os.getenv("UPSTASH_REDIS_URL")
if not redis_url:
    redis_host = os.getenv("REDIS_HOST")
    redis_port = os.getenv("REDIS_PORT")
    redis_password = os.getenv("REDIS_PASSWORD")
    if redis_host and redis_port:
        redis_url = f"rediss://{':' + redis_password + '@' if redis_password else ''}{redis_host}:{redis_port}"
    else:
        raise ValueError("Variáveis de ambiente Redis não configuradas")

# --- NOVA FUNÇÃO DEPENDÊNCIA para obter o cliente Redis ---
async def get_redis_client():
    try:
        # Cria um novo cliente (ou obtém de um pool gerenciado pela biblioteca)
        # para cada requisição que precisar dele.
        # A biblioteca redis.asyncio gerencia o pool de conexões por baixo dos panos.
        client = redis.from_url(redis_url, decode_responses=True)
        # Verifica a conexão rapidamente (opcional, mas bom para debug inicial)
        # await asyncio.wait_for(client.ping(), timeout=1.0)
        yield client # Disponibiliza o cliente para a rota
    except redis.RedisError as e:
        logger.error(f"Falha ao obter conexão Redis: {e}")
        raise HTTPException(status_code=503, detail=f"Serviço Redis indisponível: {e}")
    except asyncio.TimeoutError:
        logger.error("Timeout ao conectar/pingar Redis.")
        raise HTTPException(status_code=504, detail="Timeout ao conectar ao serviço Redis.")
    except Exception as e:
        logger.error(f"Erro inesperado ao obter cliente Redis: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao conectar ao Redis: {e}")
    # A conexão do pool é geralmente liberada automaticamente aqui,
    # mas um 'finally' com 'await client.close()' poderia ser adicionado se necessário.
    # No entanto, com from_url, a gestão do pool deve ser suficiente.

# Define um tipo anotado para facilitar a injeção
RedisClientDep = Annotated[redis.Redis, Depends(get_redis_client)]
# --------------------------------------------------------

# --- CORS (Mantido para Docker local) ---
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serviços
openai_service = OpenAIService()


@app.get("/")
async def root():
    return {"message": "SDR Agent Backend API is running!"}

# --- AJUSTE: Injeta o cliente Redis usando Depends ---
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, redis_client: RedisClientDep):
    try:
        session_id = request.session_id
        user_message = request.message
        logger.info(f"Processando chat para session_id: {session_id}")

        # Usa o cliente injetado
        thread_id = await redis_client.get(session_id)
        if not thread_id:
            logger.info(f"Thread ID não encontrado para {session_id}, criando novo.")
            thread_id = openai_service.create_thread()
            await redis_client.set(session_id, thread_id, ex=86400)
            logger.info(f"Novo thread_id {thread_id} salvo para {session_id}")
        else:
            logger.info(f"Thread ID {thread_id} encontrado para {session_id}")

        ai_response_content = await openai_service.get_assistant_response(thread_id, user_message)
        return ChatResponse(
            response=ai_response_content,
            session_id=session_id,
            thread_id=thread_id
        )
    except Exception as e:
        logger.error(f"Error processing chat for session {session_id}: {e}", exc_info=True)
        detail = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'): detail = f"{str(e)} - Response: {e.response.text}"
        elif isinstance(e, redis.RedisError): detail = f"Redis Error: {str(e)}" # Captura erros específicos do Redis
        raise HTTPException(status_code=500, detail=f"Error processing chat: {detail}")

# --- AJUSTE: Injeta o cliente Redis ---
@app.get("/api/history/{session_id}")
async def get_history(session_id: str, redis_client: RedisClientDep): # <-- Injeta aqui
    thread_id = await redis_client.get(session_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        # ... (lógica para buscar mensagens da OpenAI - sem alterações) ...
        messages = openai_service.client.beta.threads.messages.list(thread_id=thread_id)
        formatted_messages = []
        for msg in reversed(messages.data):
            if msg.content and len(msg.content) > 0 and hasattr(msg.content[0], 'text'):
                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content[0].text.value,
                    "timestamp": msg.created_at
                })
        return formatted_messages
    except Exception as e:
        logger.error(f"Error retrieving history for session {session_id}, thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving history: {str(e)}")

@app.post("/api/session")
async def create_session():
    # Esta rota não precisa do Redis
    session_id = str(uuid.uuid4())
    logger.info(f"Gerado novo session_id: {session_id}")
    return { "session_id": session_id, "message": "New session ID generated." }

# --- AJUSTE: Injeta o cliente Redis ---
@app.delete("/session/{session_id}")
async def delete_session(session_id: str, redis_client: RedisClientDep): # <-- Injeta aqui
    thread_id = await redis_client.get(session_id)
    if thread_id:
        try:
            deleted_count = await redis_client.delete(session_id)
            if deleted_count > 0: logger.info(f"Session {session_id} deleted from Redis.")
            else: logger.warning(f"Session {session_id} failed to delete from Redis.")
            openai_service.cleanup_thread(thread_id)
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}, thread {thread_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error cleaning up session: {str(e)}")
        return {"message": "Session deleted successfully"}
    else:
        logger.warning(f"Attempted to delete non-existent session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")

# --- AJUSTE: Injeta o cliente Redis ---
@app.post("/api/session/{session_id}/reset")
async def reset_session(session_id: str, redis_client: RedisClientDep): # <-- Injeta aqui para passar para delete_session
    try:
        # Passa o cliente injetado para a função delete_session (requer ajuste em delete_session)
        # Ou mais simples: refaz a lógica aqui
        thread_id = await redis_client.get(session_id)
        if thread_id:
            await redis_client.delete(session_id)
            openai_service.cleanup_thread(thread_id)
            logger.info(f"Session {session_id} reset (deleted).")
            return { "message": "Sessão resetada.", "session_id": session_id }
        else:
            logger.info(f"Session {session_id} not found for reset.")
            return { "message": "Sessão não encontrada para resetar.", "session_id": session_id }

    except Exception as e:
        logger.error(f"Error resetting session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error resetting session: {str(e)}")


# --- AJUSTE: Injeta o cliente Redis ---
@app.get("/api/health")
async def health_check(redis_client: RedisClientDep): # <-- Injeta aqui
    redis_status = "disconnected"
    try:
        # Usa o cliente injetado para o ping
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        redis_status = "connected"
    except asyncio.TimeoutError:
        logger.warning("Health check: Redis ping timed out.")
    except Exception as e:
        logger.warning(f"Health check: Redis ping failed: {e}")
    return {
        "status": "healthy" if redis_status == "connected" else "degraded",
        "services": { "redis": redis_status }
    }
