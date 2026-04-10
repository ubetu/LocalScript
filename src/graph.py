from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt, Command

from .schema import (
    State, QuestionsSchema, TestSchema
)
from .config import (
    QUESTIONS_PROMPT, PLAN_PROMPT, CODER_PROMPT, TESTER_PROMPT
)
from .client import llm_client
from .lua_utils import run_luacheck, LuaCheckResult
from .lua_tests import run_tests, TestCase, TestSuiteResult


def build_graph() -> CompiledStateGraph:
    async def ask(state: State) -> dict:
        response = await llm_client.with_structured_output(QuestionsSchema).ainvoke([SystemMessage(QUESTIONS_PROMPT), *state['messages']])
        assert isinstance(response, QuestionsSchema)
        if response.questions:
            answer = interrupt(response.questions)
            return {"messages": [response, HumanMessage(answer)]}
        else:
            return {}

    
    async def plan(state: State) -> dict:
        messages = [SystemMessage(PLAN_PROMPT), *state['messages']]
        response = await llm_client.ainvoke(messages)
        return {"plan": response.content}
    
    async def add_tests(state: State) -> dict:
        response = await llm_client.with_structured_output(TestSchema).ainvoke([SystemMessage(TESTER_PROMPT), AIMessage(f"План: {state['plan']}")])
        assert isinstance(response, TestSchema)
        return {"tests": response}
    
    def format_linter_result(linter_result: LuaCheckResult):
        pass #TODO: implement

    def format_test_result(test_result: TestSuiteResult):
        pass #TODO: implement
    
    async def code(state: State) -> dict:
        messages = [SystemMessage(CODER_PROMPT), AIMessage(f"План: {state['plan']}")]
        if state["linter_result"] and not state["linter_result"]:
            messages.append(format_linter_result(state["linter_result"]))
        elif state["test_result"] and state["test_result"].passed != state["test_result"].total:
            messages.append(format_test_result(state["test_result"]))

        response = await llm_client.ainvoke(messages)
        return {"code": response}
    
    async def test(state: State) -> Command:
        linter_result = await run_luacheck(
            state['code'], 'whatisconfig?' #TODO: add config
        )
        update = {'linter_result': linter_result, 'test_result': None}
        if not linter_result.passed:
            return Command(update=update, goto='code')

        #TODO: maybe we have only one test case
        test_result = await run_tests([
            TestCase(
                name="", #TODO: remove name from test cases
                code=state["code"],
                context_json=state["test"].input,
                expected_lua=state["test"].output
            )
        ])

        update['test_result'] = test_result
        if test_result.passed != test_result.total:
            return Command(update=update, goto='code')
        return Command(goto=END)





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


