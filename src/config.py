import os
# OLLAMA
OLLAMA_BASE_URL = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = 'qwen2.5-coder:7b-instruct-q6_K'
