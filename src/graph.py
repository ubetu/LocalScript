import logging
import re
from functools import wraps

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt, Command

from .schema import State, QuestionsSchema, TaskEntities
from .prompts import (
    ASK_MISSING_PROMPT,
    ASK_CLARIFY_PROMPT,
    EXTRACT_PROMPT,
    GENERATE_CODE_PROMPT,
    MODIFY_CODE_PROMPT,
    FIX_CODE_PROMPT,
    EXTRACT_AFTER_ASK_PROMPT,
)
from .client import llm_client
from .lua import LuaCheckResult, LuaRunResult, run_lua, run_luacheck, wrap_lua_code

logger = logging.getLogger(__name__)

MAX_FIX_TRIES = 5


def build_user_message(
    task: str,
    possible_input: str | None,
    code: str | None = None,
    static_result: LuaCheckResult | None = None,
    dynamic_result: LuaRunResult | None = None,
) -> str:
    """Build user message for code nodes of the graph. All inputs should be getted from the state."""
    parts = [f"Task: {task}"]
    if possible_input:
        parts.append(f"Possible input:\n{possible_input}")
    if code:
        parts.append(f"Current code:\n```lua\n{code}\n```")
    if static_result and not static_result.passed:
        errors = [
            f"- {error.type}: {error.message}, line {error.message.line}, column {error.message.column}"
            for error in static_result.errors
        ]
        warnings = [
            f"- {warning.type}: {warning.message}, line {warning.message.line}, column {warning.message.column}"
            for warning in static_result.warnings
        ]
        if errors or warnings:
            text = "Static checker output:\n"
            if warnings:
                text += "Warnings:\n" + "\n".join(warnings)
            if errors:
                text += "Errors:\n" + "\n".join(errors)
            parts.append(text)

    if dynamic_result and not dynamic_result.success:
        text = "Runtime error"
        if dynamic_result.line:
            text += f" on code line: {dynamic_result.line}\n"
        text += f"has an error: {dynamic_result.error}"
        parts.append(text)

    return "\n\n".join(parts)


def _parse_code(text: str) -> str:
    """Parse code from the analysis-code shama (check prompts)."""
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
    raise RuntimeError()


def _repeat(times: int, fallback=lambda _: dict()):
    """Call a function *times* times while it raises errors. If after that the function still produces errors, calls fallback"""

    def decorator_repeat(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, times + 1):
                try:
                    result = await func(*args, **kwargs)
                    return result
                except GraphInterrupt:
                    raise
                except Exception as e:
                    logger.warning(
                        f"{func.__name__}: attempt {attempt}/{times} failed ({type(e).__name__}: {e})"
                    )
            logger.warning(
                f"{func.__name__}: all {times} attempts exhausted, calling fallback"
            )
            return fallback(*args)

        return wrapper

    return decorator_repeat


def build_graph() -> CompiledStateGraph:
    # EXTRACTION

    async def _extract(state: State, system_prompt: str) -> dict:
        response = await llm_client.with_structured_output(TaskEntities).ainvoke(
            [SystemMessage(system_prompt), *state["messages"]]
        )
        assert isinstance(response, TaskEntities)

        result = {
            "code": response.code,
            "possible_input": response.possible_input,
            "task": response.task,
            "json_key": response.json_key,
            "fix_attempts": 0,
        }
        logger.info(
            f"extract: task={bool(response.task)}, has_code={response.code is not None}, has_possible_input={response.possible_input is not None}"
        )
        return result

    @_repeat(times=6, fallback=lambda state, _: {"task": state["messages"]})
    async def first_extract(state: State) -> dict:
        """Extracts info from a first message"""
        logger.debug("entering first_extract")
        return await _extract(state, EXTRACT_PROMPT)

    @_repeat(times=3)
    async def extract_after_QA(state: State) -> dict:
        """Extracts info after QA but only in a first session"""
        logger.debug("entering extract_after_QA")
        return await _extract(state, EXTRACT_AFTER_ASK_PROMPT)

    def extract_next_round(state: State) -> dict:
        """Extracts info from next rouns"""
        logger.debug("entering extract_next_round")
        return {"task": state["messages"][-1].content}

    # QA

    async def _ask(state: State, system_prompt: str) -> dict:
        response = await llm_client.with_structured_output(QuestionsSchema).ainvoke(
            [SystemMessage(system_prompt), *state["messages"]]
        )

        assert isinstance(response, QuestionsSchema)

        if response.questions:
            logger.info(f"ask: {len(response.questions)} questions generated")
            response_str = "\n".join(
                f"{i}. {q}" for i, q in enumerate(response.questions, 1)
            )
            answer = interrupt(response_str)
            return {"messages": [AIMessage(response_str), HumanMessage(answer)]}
        else:
            logger.info("ask: no questions needed, skipping")
            return {}

    @_repeat(times=3)
    async def ask_to_clarify(state: State) -> dict:
        return await _ask(state, ASK_CLARIFY_PROMPT)

    @_repeat(times=3)
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
        logger.debug(f"code generated: {code.count(chr(10)) + 1} lines")
        return {"code": code}

    @_repeat(times=10)
    async def generate_code(state: State) -> dict:
        logger.debug("entering generate_code")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possible_input"],
        )
        code_result = await _code(GENERATE_CODE_PROMPT, user_message)
        code_result["fix_attempts"] = 0
        return code_result

    @_repeat(times=6)
    async def modify_code(state: State) -> dict:
        logger.debug("entering modify_code")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possible_input"],
            code=state["code"],
        )
        code_result = await _code(MODIFY_CODE_PROMPT, user_message)
        code_result["fix_attempts"] = 0
        return code_result

    @_repeat(times=6)
    async def fix_code(state: State) -> dict:
        logger.info(f"entering fix_code, fix_attempts={state.get('fix_attempts', 0)}")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state["possible_input"],
            code=state["code"],
            static_result=state["static_result"],
            dynamic_result=state["dynamic_result"],
        )

        return await _code(FIX_CODE_PROMPT, user_message)

    async def test(state: State) -> Command:
        static_result = None
        try:
            static_result = await run_luacheck(state["code"])  # type: ignore
        except Exception:
            pass

        dynamic_result = None
        if state["possible_input"] is not None:
            try:
                dynamic_result = await run_lua(state["code"], state["possible_input"])  # type: ignore
            except Exception:
                pass

        if static_result is not None:
            logger.info(
                f"test: static check passed={static_result.passed}, errors={len(static_result.errors)}, warnings={len(static_result.warnings)}"
            )
        else:
            logger.info("test: static check skipped")

        if dynamic_result is not None:
            if dynamic_result.success:
                logger.info("test: dynamic check passed")
            else:
                logger.info(f"test: dynamic check failed, error={dynamic_result.error}")
        else:
            logger.info("test: dynamic check skipped")

        if (static_result is None or static_result.passed) and (
            dynamic_result is None or dynamic_result.success
        ):
            logger.info("test: all checks passed, going to format_code")
            return Command(goto="format_code")
        fix_attempts = state.get("fix_attempts", 0) + 1
        if fix_attempts >= MAX_FIX_TRIES:
            logger.warning(
                f"test: max fix attempts ({MAX_FIX_TRIES}) reached, going to format_code"
            )
            return Command(goto="format_code")
        logger.info(
            f"test: checks failed, going to fix_code (attempt {fix_attempts}/{MAX_FIX_TRIES})"
        )
        return Command(
            update={
                "static_result": static_result,
                "fix_attempts": fix_attempts,
                "dynamic_result": dynamic_result,
            },
            goto="fix_code",
        )

    def format_code(state: State) -> dict:
        logger.info(
            f"format_code: formatting output, code length={len(state['code'])} chars" # type: ignore
        )
        key = state.get("json_key") or "result"
        formatted = wrap_lua_code(key, state['code'])  # type: ignore
        logger.info(f"format_code: output={formatted}")
        return {"formatted_output": formatted}

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
    builder.add_node("format_code", format_code)

    builder.add_conditional_edges(
        START,
        lambda state: len(state["messages"]) > 1,
        {True: "extract_next_round", False: "first_extract"},
    )
    builder.add_conditional_edges(
        "first_extract",
        lambda state: state.get("possible_input") is None,
        {True: "ask_missing_info", False: "ask_to_clarify"},
    )
    builder.add_edge("ask_missing_info", "ask_to_clarify")
    builder.add_edge("ask_to_clarify", "extract_after_QA")
    builder.add_conditional_edges(
        "extract_after_QA",
        lambda state: state.get("code") is None,
        {True: "generate_code", False: "modify_code"},
    )
    builder.add_edge("generate_code", "test")
    builder.add_edge("modify_code", "test")
    builder.add_edge("fix_code", "test")
    builder.add_edge("format_code", END)

    serde = JsonPlusSerializer(allowed_msgpack_modules=[
        ("src.lua.lua_utils", "LuaIssueSeverity"),
        ("src.lua.lua_utils", "LuaIssueMessage"),
        ("src.lua.lua_utils", "LuaIssue"),
        ("src.lua.lua_utils", "LuaCheckResult"),
        ("src.lua.lua_tests", "LuaRunResult"),
    ])
    return builder.compile(checkpointer=MemorySaver(serde=serde))


graph = build_graph()
