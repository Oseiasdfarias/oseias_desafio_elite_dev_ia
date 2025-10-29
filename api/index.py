from fastapi import FastAPI, HTTPException
# Remova CORSMiddleware se estiver fazendo deploy na Vercel ou usando Nginx proxy
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict # Remova List se não usada
from dotenv import load_dotenv
import uuid
import logging
import os # Necessário para getenv
import redis.asyncio as redis # <-- Importa Redis Assíncrono

load_dotenv() # Carrega .env

from models import ChatRequest, ChatResponse
from services import OpenAIService

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- Configuração do Cliente Redis ---
redis_url = os.getenv("UPSTASH_REDIS_URL") # Pega a URL completa do Upstash
# Alternativa se você definiu host/port/password separadamente:
# redis_host = os.getenv("REDIS_HOST", "localhost")
# redis_port = int(os.getenv("REDIS_PORT", 6379))
# redis_password = os.getenv("REDIS_PASSWORD", None)

if not redis_url:
    # Se a URL completa não estiver definida, tenta montar com partes separadas
    redis_host = os.getenv("REDIS_HOST")
    redis_port = os.getenv("REDIS_PORT")
    redis_password = os.getenv("REDIS_PASSWORD")
    if redis_host and redis_port:
        redis_url = f"rediss://{':' + redis_password + '@' if redis_password else ''}{redis_host}:{redis_port}"
    else:
        raise ValueError("Variáveis de ambiente Redis não configuradas (UPSTASH_REDIS_URL ou REDIS_HOST/PORT/PASSWORD)")

try:
    # Cria o cliente Redis assíncrono
    redis_client = redis.from_url(redis_url, decode_responses=True)
    logger.info(f"Conectado ao Redis em {redis_url.split('@')[-1]}") # Log sem a senha
except Exception as e:
    logger.error(f"Falha ao conectar ao Redis: {e}")
    # Decide se quer parar a aplicação ou tentar continuar (pode falhar depois)
    raise RuntimeError(f"Não foi possível conectar ao Redis: {e}")

# (Opcional) Eventos de startup/shutdown para testar/fechar conexão
# @app.on_event("startup")
# async def startup_event():
#     try:
#         await redis_client.ping()
#         logger.info("Ping no Redis bem-sucedido.")
#     except Exception as e:
#         logger.error(f"Ping no Redis falhou: {e}")

# @app.on_event("shutdown")
# async def shutdown_event():
#     await redis_client.close()
#     logger.info("Conexão Redis fechada.")


# --- CORS (Mantenha se rodando localmente sem Nginx/Docker, remova para Vercel) ---
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001", # Adicionei 3001
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001", # Adicionei 3001
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---------------------------------------------------------------------------------


# Initialize services
openai_service = OpenAIService()

# REMOVA o dicionário 'sessions' em memória
# sessions: Dict[str, str] = {}

@app.get("/")
async def root():
    # Ajuste a mensagem se necessário (ex: API Endpoint)
    return {"message": "SDR Agent Backend API is running!"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id
        user_message = request.message
        
        logger.info(f"Processando chat para session_id: {session_id}")
        
        # --- Lógica do Redis ---
        thread_id = await redis_client.get(session_id) # Busca no Redis

        if not thread_id:
            logger.info(f"Thread ID não encontrado para {session_id} no Redis, criando novo.")
            thread_id = openai_service.create_thread()
            # Salva no Redis com um tempo de expiração (ex: 1 dia = 86400 segundos)
            await redis_client.set(session_id, thread_id, ex=86400)
            logger.info(f"Novo thread_id {thread_id} salvo no Redis para {session_id} (expira em 1 dia)")
        else:
            logger.info(f"Thread ID {thread_id} encontrado no Redis para {session_id}")
        # --------------------

        ai_response_content = await openai_service.get_assistant_response(thread_id, user_message)

        return ChatResponse(
            response=ai_response_content,
            session_id=session_id,
            thread_id=thread_id
        )
    except Exception as e:
        logger.error(f"Error processing chat for session {session_id}: {e}", exc_info=True)
        detail = str(e)
        # Tenta extrair detalhes de erros Redis ou HTTP
        if hasattr(e, 'response') and hasattr(e.response, 'text'): detail = f"{str(e)} - Response: {e.response.text}"
        elif isinstance(e, redis.RedisError): detail = f"Redis Error: {str(e)}"
        raise HTTPException(status_code=500, detail=f"Error processing chat: {detail}")

@app.get("/history/{session_id}")
async def get_history(session_id: str):
    # Substitui a busca no dicionário pela busca no Redis
    thread_id = await redis_client.get(session_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail="Session not found in Redis")
    
    # O resto da lógica permanece igual
    try:
        messages = openai_service.client.beta.threads.messages.list(thread_id=thread_id)
        formatted_messages = []
        for msg in reversed(messages.data):
            # Pequena melhoria: checa se content[0] existe antes de acessar text
            if msg.content and len(msg.content) > 0 and hasattr(msg.content[0], 'text'):
                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content[0].text.value,
                    "timestamp": msg.created_at # Mantém timestamp original
                })
        return formatted_messages
    except Exception as e:
        logger.error(f"Error retrieving history for session {session_id}, thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving history: {str(e)}")

@app.post("/session")
async def create_session():
    """Gera um novo session_id. O thread será criado no primeiro /chat."""
    session_id = str(uuid.uuid4())
    logger.info(f"Gerado novo session_id: {session_id}")
    # Não interage com Redis ou OpenAI aqui
    return {
        "session_id": session_id,
        "message": "New session ID generated. Thread will be created on first message."
    }

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Deleta a sessão do Redis e o thread da OpenAI"""
    thread_id = await redis_client.get(session_id) # Busca primeiro para pegar o thread_id
    if thread_id:
        try:
            deleted_count = await redis_client.delete(session_id) # Deleta do Redis
            if deleted_count > 0:
                logger.info(f"Session {session_id} deleted from Redis.")
            else:
                logger.warning(f"Session {session_id} found initially but failed to delete from Redis.")

            # Tenta deletar da OpenAI mesmo se a deleção do Redis falhar
            openai_service.cleanup_thread(thread_id)
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}, thread {thread_id}: {e}", exc_info=True)
            # Retorna um erro 500 se a limpeza falhar
            raise HTTPException(status_code=500, detail=f"Error cleaning up session: {str(e)}")
        return {"message": "Session deleted successfully"}
    else:
        logger.warning(f"Attempted to delete non-existent session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")

@app.post("/session/{session_id}/reset")
async def reset_session(session_id: str):
    """Reseta uma sessão deletando o thread antigo e a chave Redis."""
    # Reutiliza a lógica de deleção, que já trata o caso de não encontrar
    try:
        delete_response = await delete_session(session_id)
        # Se delete_session não levantou exceção 404, significa que existia e foi deletada (ou tentou ser)
        return {
            "message": "Sessão resetada com sucesso. O próximo chat criará um novo thread.",
            "session_id": session_id
        }
    except HTTPException as http_exc:
        # Se a sessão não foi encontrada (404), o reset não faz sentido prático, mas podemos informar
        if http_exc.status_code == 404:
            return {
                "message": "Sessão não encontrada para resetar. O próximo chat criará um novo thread.",
                "session_id": session_id
            }
        else:
            raise http_exc # Re-levanta outros erros HTTP


# Removido /sessions pois listar todas as chaves do Redis pode ser custoso/inseguro
# @app.get("/sessions") ...

# Health check endpoint ajustado
@app.get("/health")
async def health_check():
    redis_status = "disconnected"
    try:
        # Tenta um comando rápido no Redis para verificar a conexão
        await redis_client.ping()
        redis_status = "connected"
    except Exception as e:
        logger.warning(f"Health check: Redis ping failed: {e}")

    # Não temos mais a contagem de sessões em memória
    return {
        "status": "healthy" if redis_status == "connected" else "degraded",
        "services": {
            "openai": "configured",
            "pipefy": "configured",
            "calendar": "configured",
            "redis": redis_status # Adiciona status do Redis
        }
    }
