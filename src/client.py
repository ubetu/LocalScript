from langchain_ollama import ChatOllama
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL

llm_client = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, num_ctx=4096, num_predict=256)
