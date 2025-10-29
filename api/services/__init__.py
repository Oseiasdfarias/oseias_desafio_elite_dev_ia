# backend/services/__init__.py

"""
Este pacote inicializa e exporta as classes de serviço
para que possam ser facilmente importadas pelo resto da aplicação.

Exemplo em main.py:
from services import OpenAIService
"""

from .openai_service import OpenAIService
from .pipefy_service import PipefyService
from .calendar_service import CalendarService

# Opcional: define o que é exportado quando se faz "from services import *"
__all__ = [
    "OpenAIService",
    "PipefyService",
    "CalendarService"
]