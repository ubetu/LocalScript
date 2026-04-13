"""
Integration tests for the full Lua validation pipeline (luacheck + AST validator).
No mocks — requires luacheck to be installed and accessible in PATH.
"""
import asyncio
import shutil
import textwrap

import pytest

from lua_parser import validate_lua


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Skip the whole module when luacheck is not installed
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    shutil.which("luacheck") is None,
    reason="luacheck not installed",
)

CONFIG = "resources/luacheckrc.lua"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_types(result):
    return {issue.type for issue in result.errors}


def _warning_types(result):
    return {issue.type for issue in result.warnings}


def _messages(issues):
    return [issue.message.message for issue in issues]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_simple_expression():
    result = run(validate_lua("return wf.vars.x + 1", CONFIG))
    assert result.passed
    assert result.errors == []
    assert result.warnings == []


def test_valid_complex_script():
    code = textwrap.dedent("""\
    local result = {}
    for _, item in ipairs(wf.vars.items) do
        if type(item) == "table" then
            table.insert(result, item)
        end
    end
    return result
    """)
    result = run(validate_lua(code, CONFIG))
    assert result.passed
    assert result.errors == []


# ---------------------------------------------------------------------------
# Warnings (both layers produce warnings, overall still passes)
# ---------------------------------------------------------------------------

def test_print_warns_from_both_layers():
    """print: WARN_GLOBAL from AST + W113 from luacheck. luacheck exits 1 for warnings → not passed."""
    result = run(validate_lua('print("hello")', CONFIG))
    assert not result.passed
    assert result.errors == []
    # AST layer: WARN_GLOBAL
    assert "WARN_GLOBAL" in _warning_types(result)
    # luacheck layer: W113 (accessing undefined variable)
    assert "W113" in _warning_types(result)
    assert len(result.warnings) == 2


def test_assert_warns_from_both_layers():
    """assert: WARN_GLOBAL from AST + W113 from luacheck."""
    result = run(validate_lua('assert(wf.vars.x ~= nil, "expected x")', CONFIG))
    assert not result.passed
    assert result.errors == []
    assert "WARN_GLOBAL" in _warning_types(result)
    assert "W113" in _warning_types(result)


# ---------------------------------------------------------------------------
# Forbidden globals — caught by both layers
# ---------------------------------------------------------------------------

def test_os_rejected_by_both_layers():
    result = run(validate_lua("return os.time()", CONFIG))
    assert not result.passed
    # AST: FORBIDDEN_GLOBAL error
    assert "FORBIDDEN_GLOBAL" in _error_types(result)
    assert any("os" in m for m in _messages(result.errors))
    # luacheck: W113 warning (undefined 'os')
    assert "W113" in _warning_types(result)


def test_io_rejected_by_both_layers():
    result = run(validate_lua('io.write("hello")', CONFIG))
    assert not result.passed
    assert "FORBIDDEN_GLOBAL" in _error_types(result)
    assert any("io" in m for m in _messages(result.errors))
    assert "W113" in _warning_types(result)


def test_require_rejected_by_both_layers():
    result = run(validate_lua('local json = require("json")', CONFIG))
    assert not result.passed
    assert "FORBIDDEN_GLOBAL" in _error_types(result)
    assert any("require" in m for m in _messages(result.errors))
    assert "W113" in _warning_types(result)


# ---------------------------------------------------------------------------
# AST-only forbidden constructs (luacheck may or may not flag these)
# ---------------------------------------------------------------------------

def test_goto_rejected_by_ast():
    result = run(validate_lua("::start:: goto start", CONFIG))
    assert not result.passed
    assert "FORBIDDEN_CONSTRUCT" in _error_types(result)


# ---------------------------------------------------------------------------
# luacheck-only issues (AST validator doesn't catch these)
# ---------------------------------------------------------------------------

def test_luacheck_catches_never_set_local():
    """W221: local declared but never assigned — AST validator ignores this."""
    code = "local x\nreturn x"
    result = run(validate_lua(code, CONFIG))
    assert not result.passed
    assert result.errors == []  # AST has no errors
    assert "W221" in _warning_types(result)


def test_luacheck_catches_redefined_local():
    """W421: variable shadowing — AST validator ignores this."""
    code = textwrap.dedent("""\
    local x = 1
    do
        local x = 2
        return x
    end
    """)
    result = run(validate_lua(code, CONFIG))
    # luacheck flags W421 (shadowing)
    assert "W421" in _warning_types(result)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_syntax_error_fails_both():
    result = run(validate_lua("if then end end end", CONFIG))
    assert not result.passed
    assert result.exit_code == 2
    assert any(issue.type == "PARSE_ERROR" for issue in result.errors)


def test_empty_code_passes():
    result = run(validate_lua("", CONFIG))
    assert result.passed


def test_comment_only_passes():
    result = run(validate_lua("-- just a comment", CONFIG))
    assert result.passed
    assert result.errors == []
    assert result.warnings == []
