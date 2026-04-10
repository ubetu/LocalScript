from ollama import AsyncClient
from .config import OLLAMA_HOST

ollama_client = AsyncClient(host=OLLAMA_HOST)