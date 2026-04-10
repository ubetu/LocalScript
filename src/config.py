import os
from pathlib import Path
# OLLAMA
OLLAMA_BASE_URL = os.environ['OLLAMA_HOST']
OLLAMA_MODEL = 'qwen2.5-coder:7b-instruct-q6_K'


# PROMPTS
_PROMPTS_DIR = Path('prompts')
QUESTIONS_PROMPT =( _PROMPTS_DIR / 'questions.txt').read_text(encoding="utf-8")
PLAN_PROMPT =( _PROMPTS_DIR / 'plan.txt').read_text(encoding="utf-8")
CODER_PROMPT =( _PROMPTS_DIR / 'coder.txt').read_text(encoding="utf-8")
TESTER_PROMPT =( _PROMPTS_DIR / 'coder.txt').read_text(encoding="utf-8")

