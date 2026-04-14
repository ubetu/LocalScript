from langchain_ollama import ChatOllama
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL

llm_client = ChatOllama(
    base_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    num_ctx=4096,
    num_predict=1024,
    temperature=0.1,
    top_p=0.9,
    top_k=20,
    repeat_penalty=1.1,
)
