import asyncio
import pytest
from lua.lua_tests import run_lua, LuaRunResult

EMPTY_CTX = '{"wf":{}}'


def run(coro):
    return asyncio.run(coro)


def test_success_returns_number():
    r = run(run_lua("return 1 + 1", EMPTY_CTX))
    assert r.success is True
    assert r.output == "2"
    assert r.error is None


def test_success_returns_string():
    r = run(run_lua('return "hello"', EMPTY_CTX))
    assert r.success is True
    assert r.output == '"hello"'


def test_success_reads_context():
    ctx = '{"wf":{"vars":{"emails":["a@x.com","b@x.com"]}}}'
    r = run(run_lua("return wf.vars.emails[#wf.vars.emails]", ctx))
    assert r.success is True
    assert r.output == '"b@x.com"'


def test_success_returns_table():
    r = run(run_lua("return {a = 1, b = 2}", EMPTY_CTX))
    assert r.success is True
    assert r.output is not None


def test_no_output_nil_return():
    r = run(run_lua("local x = 1", EMPTY_CTX))
    assert r.success is False
    assert r.error is not None
    assert r.line is None


def test_load_error_syntax():
    r = run(run_lua("return if", EMPTY_CTX))
    assert r.success is False
    assert r.error is not None
    assert r.line == 1


def test_runtime_error_nil_arithmetic():
    r = run(run_lua("return nil + 1", EMPTY_CTX))
    assert r.success is False
    assert r.error is not None
    assert r.line == 1


def test_runtime_error_line_number():
    code = "local x = 1\nlocal y = 2\nreturn x + nil"
    r = run(run_lua(code, EMPTY_CTX))
    assert r.success is False
    assert r.line == 3


def test_utils_array_available():
    r = run(run_lua(
        "local a = _utils.array.new()\ntable.insert(a, 1)\nreturn a",
        EMPTY_CTX,
    ))
    assert r.success is True
