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

from .schema import State, QuestionsSchema, TaskEntities, ReviewResult
from .prompts import (
    ASK_MISSING_PROMPT,
    ASK_CLARIFY_PROMPT,
    EXTRACT_PROMPT,
    GENERATE_CODE_PROMPT,
    MODIFY_CODE_PROMPT,
    FIX_CODE_PROMPT,
    REVIEW_CODE_PROMPT,
    EXTRACT_AFTER_ASK_PROMPT,
)
from .client import llm_client
from .lua import LuaCheckResult, LuaRunResult, run_lua, run_luacheck, wrap_lua_code

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
logger.addHandler(_handler)

MAX_FIX_TRIES = 10


def build_user_message(
    task: str,
    possible_input: str | None,
    code: str | None = None,
    static_result: LuaCheckResult | None = None,
    dynamic_result: LuaRunResult | None = None,
    review_result: ReviewResult | None = None,
) -> str:
    """Build user message for code nodes of the graph. All inputs should be getted from the state."""
    parts = [f"Task: {task}"]
    if possible_input:
        parts.append(f"Possible input:\n{possible_input}")
    if code:
        parts.append(f"Current code:\n```lua\n{code}\n```")
    if static_result and not static_result.passed:
        errors = [
            f"- {error.type} L{error.message.line}: {error.message.message}"
            for error in static_result.errors
        ]
        warnings = [
            f"- {warning.type} L{warning.message.line}: {warning.message.message}"
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

    if review_result and not review_result.is_correct and review_result.concerns:
        parts.append(
            f"Code review concerns:\n{review_result.concerns}\n\n"
            "The code runs without errors but does not correctly solve the task. "
            "Fix the logic to address the concerns above."
        )

    return "\n\n".join(parts)


def _fmt_messages(messages: list) -> str:
    """Format a list of LangChain messages into a readable debug string."""
    parts = []
    for m in messages:
        role = type(m).__name__.replace("Message", "").upper()
        content = str(m.content)
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _parse_code(text: str) -> str:
    """Parse code from the analysis-code shama (check prompts)."""
    # TODO: here we can return that text format is incorrect
    match = re.search(r"```lua\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return _strip_fences(match.group(1).strip())
    if "CODE:" in text:
        after = text.split("CODE:", 1)[1]
        match = re.search(r"```\w*\s*\n(.*?)```", after, re.DOTALL)
        if match:
            return _strip_fences(match.group(1).strip())
        return _strip_fences(after.strip())
    # Incomplete fence: model opened ```lua but never closed it
    match = re.search(r"```lua\s*\n(.*)", text, re.DOTALL)
    if match:
        return _strip_fences(match.group(1).strip())
    raise RuntimeError()


def _strip_fences(code: str) -> str:
    """Remove any stray markdown fence markers that leaked into extracted code."""
    code = re.sub(r"^```(?:lua)?\s*\n?", "", code)
    code = re.sub(r"\n?```\s*$", "", code)
    code = code.strip()
    # Strip trailing whitespace from each line (prevents W612 luacheck warnings
    # that models generate but can never reliably fix in a fix loop).
    code = "\n".join(line.rstrip() for line in code.splitlines())
    return code


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
        messages = [SystemMessage(system_prompt), *state["messages"]]
        print(messages)
        logger.debug("_extract ← sending to model:\n%s", _fmt_messages(messages))
        response = await llm_client.with_structured_output(TaskEntities).ainvoke(messages)
        assert isinstance(response, TaskEntities)

        logger.debug(
            "_extract → received: task=%r, json_key=%r",
            response.task if response.task else None,
            response.json_key,
        )
        logger.info(f"extract: task={bool(response.task)}")
        return {
            "task": response.task,
            "json_key": response.json_key,
            "fix_attempts": 0,
            "qa_performed": False,
        }

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
        """Extracts info from next rounds"""
        logger.debug("entering extract_next_round")
        new_task = state["task"] + f"\nUpdate of task: {state["messages"][-1].content}"
        return {"task": new_task}

    # QA

    async def _ask(state: State, system_prompt: str) -> dict:
        messages = [SystemMessage(system_prompt), *state["messages"]]
        logger.debug("_ask ← sending to model:\n%s", _fmt_messages(messages))
        response = await llm_client.with_structured_output(QuestionsSchema).ainvoke(messages)

        assert isinstance(response, QuestionsSchema)

        if response.questions:
            logger.info(f"ask: {len(response.questions)} questions generated")
            response_str = "\n".join(
                f"{i}. {q}" for i, q in enumerate(response.questions, 1)
            )
            logger.debug("_ask → model questions:\n%s", response_str)
            answer = interrupt(response_str)
            logger.debug("_ask ← user answered: %r", answer[:300] if len(answer) > 300 else answer)
            return {"messages": [AIMessage(response_str), HumanMessage(answer)], "qa_performed": True}
        else:
            logger.info("ask: no questions needed, skipping")
            logger.debug("_ask → model returned no questions, skipping interrupt")
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
        truncated = user_message[:500] + "…" if len(user_message) > 500 else user_message
        logger.debug("_code ← sending to model:\n[SYSTEM] (see prompts.py)\n[HUMAN] %s", truncated)
        response = await llm_client.ainvoke(
            [SystemMessage(system_prompt), HumanMessage(user_message)]
        )

        assert isinstance(response.content, str)

        logger.debug(
            "_code → raw response:\n%s",
            response.content 
        )
        code = _parse_code(response.content)
        logger.debug("_code → parsed code: %d lines", code.count("\n") + 1)
        return {"code": code}

    @_repeat(times=10)
    async def generate_code(state: State) -> dict:
        logger.debug("entering generate_code")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state.get("possible_input"),
        )
        code_result = await _code(GENERATE_CODE_PROMPT, user_message)
        logger.debug("generate_code → produced code (%d lines)", code_result["code"].count("\n") + 1)
        return code_result

    @_repeat(times=6)
    async def modify_code(state: State) -> dict:
        logger.debug("entering modify_code")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state.get("possible_input"),
            code=state["code"],
        )
        code_result = await _code(MODIFY_CODE_PROMPT, user_message)
        logger.debug("modify_code → produced code (%d lines)", code_result["code"].count("\n") + 1)
        return code_result

    @_repeat(times=6)
    async def fix_code(state: State) -> dict:
        logger.info(f"entering fix_code, fix_attempts={state.get('fix_attempts', 0)}")
        user_message = build_user_message(
            task=state["task"],
            possible_input=state.get("possible_input"),
            code=state["code"],
            static_result=state.get("static_result"),
            dynamic_result=state.get("dynamic_result"),
            review_result=state.get("review_result"),
        )

        code_result = await _code(FIX_CODE_PROMPT, user_message)
        logger.debug("fix_code → produced code (%d lines)", code_result["code"].count("\n") + 1)
        return code_result

    async def test(state: State) -> Command:
        static_result = None
        try:
            static_result = await run_luacheck(state["code"])  # type: ignore
        except Exception:
            pass

        dynamic_result = None
        if state.get("possible_input"):
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
            logger.info("test: all checks passed, going to review")
            return Command(
                update={"dynamic_result": dynamic_result},
                goto="review",
            )
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

    @_repeat(times=3)
    async def review(state: State) -> dict:
        logger.debug("entering review")
        parts = [f"Task: {state['task']}"]
        if state.get("possible_input"):
            parts.append(f"Possible input:\n{state['possible_input']}")
        parts.append(f"Code:\n```lua\n{state['code']}\n```")

        dynamic_result = state.get("dynamic_result")
        if dynamic_result and dynamic_result.output:
            parts.append(f"Output produced by running the code:\n{dynamic_result.output}")

        user_message = "\n\n".join(parts)

        response = await llm_client.with_structured_output(ReviewResult).ainvoke(
            [SystemMessage(REVIEW_CODE_PROMPT), HumanMessage(user_message)]
        )
        assert isinstance(response, ReviewResult)
        logger.info(f"review: is_correct={response.is_correct}, concerns={response.concerns}")
        return {"review_result": response}

    def after_review(state: State) -> str:
        review_result = state.get("review_result")
        if review_result and not review_result.is_correct:
            fix_attempts = state.get("fix_attempts", 0)
            if fix_attempts >= MAX_FIX_TRIES:
                logger.warning("review: concerns found but max fix attempts reached, proceeding to format")
                return "format_code"
            logger.info(f"review: concerns found, routing to fix_code (attempt {fix_attempts}/{MAX_FIX_TRIES})")
            return "fix_code"
        return "format_code"

    def after_clarify(state: State) -> str:
        if state.get("qa_performed", False):
            return "extract_after_QA"
        return "generate_code" if state.get("code") is None else "modify_code"

    def format_code(state: State) -> dict:
        logger.info(
            f"format_code: formatting output, code length={len(state['code'])} chars" # type: ignore
        )
        key = state.get("json_key") or "result"
        formatted = wrap_lua_code(key, state['code'])  # type: ignore
        logger.info(f"format_code: output={formatted}")
        return {"formatted_output": formatted}

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
    builder.add_node("review", review)
    builder.add_node("format_code", format_code)

    builder.add_conditional_edges(
        START,
        lambda state: len(state["messages"]) > 1,
        {True: "extract_next_round", False: "first_extract"},
    )
    builder.add_edge("extract_next_round", "modify_code")
    builder.add_conditional_edges(
        "first_extract",
        lambda state: state.get("possible_input") is None,
        {True: "ask_missing_info", False: "ask_to_clarify"},
    )
    builder.add_edge("ask_missing_info", "ask_to_clarify")
    builder.add_conditional_edges(
        "ask_to_clarify",
        after_clarify,
        {"extract_after_QA": "extract_after_QA", "generate_code": "generate_code", "modify_code": "modify_code"},
    )
    builder.add_conditional_edges(
        "extract_after_QA",
        lambda state: state.get("code") is None,
        {True: "generate_code", False: "modify_code"},
    )
    builder.add_edge("generate_code", "test")
    builder.add_edge("modify_code", "test")
    builder.add_edge("fix_code", "test")
    builder.add_conditional_edges(
        "review",
        after_review,
        {"fix_code": "fix_code", "format_code": "format_code"},
    )
    builder.add_edge("format_code", END)

    serde = JsonPlusSerializer(allowed_msgpack_modules=[
        ("src.lua.lua_utils", "LuaIssueSeverity"),
        ("src.lua.lua_utils", "LuaIssueMessage"),
        ("src.lua.lua_utils", "LuaIssue"),
        ("src.lua.lua_utils", "LuaCheckResult"),
        ("src.lua.lua_tests", "LuaRunResult"),
        ("src.schema", "ReviewResult"),
    ])
    return builder.compile(checkpointer=MemorySaver(serde=serde))


graph = build_graph()
