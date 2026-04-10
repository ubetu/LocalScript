from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from .schema import (
    State, QuestionsSchema, TestsSchema
)
from .config import (
    QUESTIONS_PROMPT, PLAN_PROMPT, CODER_PROMPT, TESTER_PROMPT
)
from .client import llm_client


def build_graph() -> CompiledStateGraph:
    async def ask(state: State) -> dict:
        response = await llm_client.with_structured_output(QuestionsSchema).ainvoke([SystemMessage(QUESTIONS_PROMPT), *state['messages']])
        assert isinstance(response, QuestionsSchema)
        if response.questions:
            answer = interrupt(response.questions)
            return {"answer": answer, "questions": response.questions}
        else:
            return {"answer": None, "questions": None}

    
    async def plan(state: State) -> dict:
        messages = [SystemMessage(PLAN_PROMPT), *state['messages']]
        if state['questions']:
            messages.append(AIMessage(f"Уточняющие вопросы: {state['questions']}"))
            messages.append(HumanMessage(f"Ответы на уточнения: {state['answer']}"))
        response = await llm_client.ainvoke(messages)
        return {"plan": response.content}
    
    async def add_tests(state: State) -> dict:
        response = await llm_client.with_structured_output(TestsSchema).ainvoke([SystemMessage(TESTER_PROMPT), AIMessage(f"План: {state['plan']}")])
        assert isinstance(response, TestsSchema)
        #TODO: there maybe we can call a func to add this tests
        return {"tests": response.model_dump()}
    
    
    async def code(state: State) -> dict:
        # TODO: add test feedback into prompt
        response = await llm_client.ainvoke([SystemMessage(CODER_PROMPT), AIMessage(f"План: {state['plan']}")])
        return {"code": response}
    
    async def test(state: State) -> dict:
        return {} #TODO: implement
    

    builder = StateGraph(State)
    builder.add_node("ask", ask)
    builder.add_node("plan", plan)
    builder.add_node("add_tests", add_tests)
    builder.add_node("code", code)
    builder.add_node("test", test)

    builder.add_edge(START, "ask")
    builder.add_edge("ask", "plan")
    builder.add_edge("plan", "add_tests")
    builder.add_edge("add_tests", "code")
    builder.add_edge("code", "test")

    return builder.compile()

graph = build_graph()


