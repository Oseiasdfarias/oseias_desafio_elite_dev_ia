from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
from dotenv import load_dotenv
import uuid
import logging

load_dotenv()

from models import ChatRequest, ChatResponse
from services import OpenAIService

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS Middleware
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
openai_service = OpenAIService()

# In-memory storage for chat sessions (thread_id by session_id)
sessions: Dict[str, str] = {}

@app.get("/")
async def root():
    return {"message": "SDR Agent Backend is running!"}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id
        user_message = request.message
        
        # Cria nova sessão se não existir (baseado no ID do cliente)
        if not session_id or session_id not in sessions:
            logger.info(f"New session received: {session_id}")
            sessions[session_id] = openai_service.create_thread()
        else:
            logger.info(f"Existing session: {session_id}")

        thread_id = sessions[session_id]

        ai_response_content = await openai_service.get_assistant_response(thread_id, user_message)

        return ChatResponse(
            response=ai_response_content,
            session_id=session_id,
            thread_id=thread_id
        )
    except Exception as e:
        logger.error(f"Error processing chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

@app.get("/history/{session_id}")
async def get_history(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        thread_id = sessions[session_id]
        messages = openai_service.client.beta.threads.messages.list(thread_id=thread_id)
        
        # Format messages in chronological order
        formatted_messages = []
        for msg in reversed(messages.data):
            if msg.content and hasattr(msg.content[0], 'text'):
                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content[0].text.value,
                    "timestamp": msg.created_at
                })
        
        return formatted_messages
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving history: {str(e)}")

@app.post("/session")
async def create_session():
    """Create a new chat session"""
    session_id = str(uuid.uuid4())
    thread_id = openai_service.create_thread()
    sessions[session_id] = thread_id
    
    return {
        "session_id": session_id,
        "thread_id": thread_id,
        "message": "New session created successfully"
    }

@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session"""
    if session_id in sessions:
        thread_id = sessions.pop(session_id)
        try:
            # Deleta o thread da OpenAI
            openai_service.cleanup_thread(thread_id)
        except Exception as e:
            logger.error(f"Error cleaning up thread: {e}")
        
        return {"message": "Session deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")

@app.post("/session/{session_id}/reset")
async def reset_session(session_id: str):
    """Reseta uma sessão problemática (cria um novo thread)"""
    if session_id in sessions:
        old_thread_id = sessions[session_id]
        
        # Deleta o thread antigo
        try:
            openai_service.cleanup_thread(old_thread_id)
        except Exception as e:
            logger.error(f"Error cleaning up old thread {old_thread_id}: {e}")

        # Criar novo thread
        new_thread_id = openai_service.create_thread()
        sessions[session_id] = new_thread_id
        
        return {
            "message": "Sessão resetada com sucesso",
            "old_thread_id": old_thread_id,
            "new_thread_id": new_thread_id
        }
    else:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

@app.get("/sessions")
async def list_sessions():
    """List all active sessions"""
    return {
        "sessions": [
            {"session_id": session_id, "thread_id": thread_id}
            for session_id, thread_id in sessions.items()
        ],
        "total_sessions": len(sessions)
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "sessions_active": len(sessions),
        "services": {
            "openai": "connected",
            "pipefy": "configured",
            "calendar": "configured"
        }
    }