from langchain_core.messages import SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from .schema import State
from .config import (
    QUESTIONS_PROMPT
)


def build_graph() -> CompiledStateGraph:
    def ask_question(state: State):
        client.