import re
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt, Command

from .schema import (
    State, QuestionsSchema, TaskEntities
)
from .prompts import (
    ASK_MISSING_PROMPT, ASK_CLARIFY_PROMPT, EXTRACT_PROMPT, GENERATE_CODE_PROMPT, MODIFY_CODE_PROMPT, FIX_CODE_PROMPT, 
    EXTRACT_AFTER_ASK_PROMPT
)
from .client import llm_client
from .lua_utils import run_luacheck, LuaCheckResult

def build_user_message(
    task: str, possible_input: str | None, code: str | None = None,
    linter_result: LuaCheckResult | None = None,
) -> str:
    parts = [f"Task: {task}"]
    if possible_input:
        parts.append(f"Possible input: possible_input")
    if code:
        parts.append(f"Current code:\n```lua\n{code}\n```")
    if linter_result:
        errors = [f"- {error.type}: {error.message}, line {error.line}, column {error.column}" for error in linter_result.errors]
        warnings = [f"- {warning.type}: {warning.message}, line {warning.line}, column {warning.column}" for warning in linter_result.warnings]
        if errors or warnings:
            text = "Linter output:\n"
            if warnings:
                text += "Warnings:\n" + "\n".join(warnings)
            if errors:
                text += "Errors:\n" + "\n".join(errors) 
            parts.append(text)

    return "\n\n".join(parts)

def _parse_code(text: str) -> str:
    # TODO: here we can return that text format is incorrect
    match = re.search(r"```lua\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if "CODE:" in text:
        after = text.split("CODE:", 1)[1]
        match = re.search(r"```\w*\s*\n(.*?)```", after, re.DOTALL)
        if match:
            return match.group(1).strip()
        return after.strip()
    return text.strip()


def build_graph() -> CompiledStateGraph:
    # EXTRACTION

    async def _extract(state: State, system_prompt: str) -> dict:
        response = await llm_client.with_structured_output(TaskEntities).ainvoke(
            [SystemMessage(system_prompt), *state['messages']]
        )
        assert isinstance(response, TaskEntities)

        return {"code": response.code, "possible_input": response.possible_input,
                "task": response.task}
    
    async def first_extract(state: State) -> dict:
        return await _extract(state, EXTRACT_PROMPT)
    
    async def extract_after_QA(state: State) -> dict:
        return await _extract(state, EXTRACT_AFTER_ASK_PROMPT)
    
    def extract_next_round(state: State) -> dict:
        return {"task": state["messages"][-1].content}
    
    # QA

    async def _ask(state: State, system_prompt: str) -> dict:
        response = await llm_client.with_structured_output(QuestionsSchema).ainvoke(
            [SystemMessage(system_prompt), *state['messages']]
        )

        assert isinstance(response, QuestionsSchema)

        if response.questions:
            response_str = "\n".join(f"{i}. {q}" for i, q in enumerate(response.questions, 1))
            answer = interrupt(response_str)
            return {"messages": [AIMessage(response_str), HumanMessage(answer)]}
        else:
            return {}
        

    async def ask_to_clarify(state: State) -> dict:
        return await _ask(state, ASK_CLARIFY_PROMPT)
    
    async def ask_missing_info(state: State) -> dict:
        missing = "- JSON context with input variables (wf.vars or wf.initVariables) is not provided"
        system_prompt = ASK_MISSING_PROMPT.format(missing_description=missing)
        return await _ask(state, system_prompt)
    
    # CODE
    
    async def _code(system_prompt: str, user_message: str) -> dict:        
        response = await llm_client.ainvoke(
            [SystemMessage(system_prompt), HumanMessage(user_message)]
        )

        assert isinstance(response.content, str)

        code = _parse_code(response.content)
        return {"code": code}
    

    async def generate_code (state: State) -> dict:
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possile_input"],
        )
        return await _code(GENERATE_CODE_PROMPT, user_message)
    
    async def modify_code (state: State) -> dict:
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possile_input"],
            code=state["code"]
            )
        return await _code(MODIFY_CODE_PROMPT, user_message)
    
    async def fix_code (state: State) -> dict:
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possile_input"],
            code=state["code"],
            linter_result=state["linter_result"] #TODO: add another checks
        )

        return await _code(FIX_CODE_PROMPT, user_message)

    async def test(state: State) -> Command:
        # TODO: add another checks
        linter_result = await run_luacheck(state["code"]) # type: ignore
        if linter_result.passed:
            return Command(goto=END)
        return Command(update={"linter_result": linter_result}, goto="fix_code")
    
    def format_code(state: State) -> str:
        # TODO: fromat code in json format
        return state["code"] # type: ignore


    # TODO: if user send existing code, it can be in json format, we want to convert it into common form
    builder = StateGraph(State)
    builder.add_node("first_extract", first_extract)
    builder.add_node("extract_after_QA", extract_after_QA)
    builder.add_node("extract_next_round", extract_next_round)
    builder.add_node("ask_missing_info", ask_missing_info)
    builder.add_node("ask_to_clarify", ask_to_clarify)
    builder.add_node("generate_code", generate_code)
    builder.add_node("modify_code", modify_code)
    builder.add_node("fix_code", fix_code)
    builder.add_node("test", test)

    builder.add_conditional_edges(START, lambda state: len(state["messages"]) > 1, {True: "extract_next_round", False: "first_extract"}) 
    builder.add_conditional_edges("first_extract", lambda state: state.possile_input is None, {True: "ask_missing_info", False: "ask_to_clarify"})
    builder.add_edge("ask_missing_info", "ask_to_clarify")
    builder.add_edge("ask_to_clarify", "extract_after_QA")
    builder.add_conditional_edges("extract_after_QA", lambda state: state.code is None, {True:"generate_code", False: "modify_code"})
    builder.add_edge("generate_code", "test")
    builder.add_edge("modify_code", "test")
    builder.add_edge("fix_code", "test")

    return builder.compile()

graph = build_graph()


