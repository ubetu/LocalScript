from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt, Command

from .schema import (
    State, QuestionsSchema, TaskEntities
)
from .prompts import (
    ASK_MISSING_PROMPT, ASK_CLARIFY_PROMPT, EXTRACT_PROMPT, GENERATE_CODE_PROMPT, MODIFY_CODE_PROMPT, FIX_CODE_PROMPT
)
from .client import llm_client


def build_graph() -> CompiledStateGraph:
    
    async def extract(state: State) -> dict:
        response = await llm_client.with_structured_output(TaskEntities).ainvoke(
            [SystemMessage(EXTRACT_PROMPT), *state['messages']]
        )
        assert isinstance(response, TaskEntities)

        return {"task_entities": response}

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

    def _parse_code(text: str) -> str:
        return '' #TODO: implement
    
    async def _code(state: State,  system_prompt: str) -> dict:        
        response = await llm_client.ainvoke(
            [SystemMessage(system_prompt), *state['messages']]
        )

        assert isinstance(response.content, str)

        code = _parse_code(response.content)
        return {"code": code}
    

    async def generate_code (state: State) -> dict:
        return await _code(state, GENERATE_CODE_PROMPT)
    
    async def modify_code (state: State) -> dict:
        return await _code(state, MODIFY_CODE_PROMPT) #TODO: fromat prompt
    
    async def fix_code (state: State) -> dict:
        return await _code(state, FIX_CODE_PROMPT) #TODO: fromat prompt

    async def test(state: State) -> dict:
        # TODO: impement it
        return {}




    builder = StateGraph(State)
    builder.add_node("extract", extract)
    builder.add_node("extract_after_missing_info", extract)
    builder.add_node("ask_missing_info", ask_missing_info)
    builder.add_node("ask_to_clarify", ask_to_clarify)
    builder.add_node("generate_code", generate_code)
    builder.add_node("modify_code", modify_code)
    builder.add_node("fix_code",  fix_code)
    builder.add_node("test", test)

    builder.add_edge(START, "extract")
    builder.add_conditional_edges("extract", lambda state: state['task_entities'].context is None, {True: "ask_missing_info", False: "ask_to_clarify"})
    builder.add_edge("ask_missing_info", "extract_after_missing_info")
    builder.add_edge("extract_after_missing_info", "ask_to_clarify")
    builder.add_conditional_edges("ask_to_clarify", lambda state: state['task_entities'].code is None, {True:"generate_code", False: "modify_code"})
    builder.add_edge("generate_code", "test")
    builder.add_edge("modify_code", "test")
    builder.add_edge("fix_code", "test")

    return builder.compile()

graph = build_graph()


