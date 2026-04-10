from langchain_ollama import ChatOllama
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL

ollama_client = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL)
