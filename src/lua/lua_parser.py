from __future__ import annotations

from luaparser import ast as lua_ast
from luaparser.ast import ASTRecursiveVisitor
from luaparser.astnodes import *  # noqa: F403

try:
    from .lua_utils import (
        LuaCheckResult,
        LuaIssue,
        LuaIssueMessage,
        LuaIssueSeverity,
        run_luacheck,
    )
except ImportError:  # pragma: no cover - supports direct script imports in tests/tools
    from lua.lua_utils import (
        LuaCheckResult,
        LuaIssue,
        LuaIssueMessage,
        LuaIssueSeverity,
        run_luacheck,
    )


ALLOWED_NODE_TYPES: set[type] = {
    Chunk,
    Block,
    Assign,
    LocalAssign,
    If,
    ElseIf,
    While,
    Fornum,
    Forin,
    Repeat,
    Return,
    Break,
    Do,
    Function,
    LocalFunction,
    Call,
    Invoke,
    Method,
    SemiColon,
    Name,
    Number,
    String,
    TrueExpr,
    FalseExpr,
    Nil,
    Table,
    Field,
    Index,
    Dots,
    Varargs,
    AnonymousFunction,
    Comment,
    AddOp,
    SubOp,
    MultOp,
    FloatDivOp,
    FloorDivOp,
    ModOp,
    ExpoOp,
    EqToOp,
    NotEqToOp,
    LessThanOp,
    GreaterThanOp,
    LessOrEqThanOp,
    GreaterOrEqThanOp,
    AndLoOp,
    OrLoOp,
    BAndOp,
    BOrOp,
    BXorOp,
    BShiftLOp,
    BShiftROp,
    UMinusOp,
    ULengthOP,
    ULNotOp,
    UBNotOp,
    Concat,
    Op,
    BinaryOp,
    UnaryOp,
    AriOp,
    RelOp,
    LoOp,
    BitOp,
    Expression,
    Statement,
    Lhs,
}

FORBIDDEN_NODE_TYPES: set[type] = {
    Goto,
    Label,
    Attribute,
}

ALLOWED_GLOBALS: set[str] = {
    "wf",
    "_utils",
    "type",
    "tonumber",
    "tostring",
    "pairs",
    "ipairs",
    "next",
    "table",
    "string",
    "math",
    "error",
    "select",
    "unpack",
    "pcall",
    "xpcall",
    "rawequal",
    "true",
    "false",
    "nil",
}

FORBIDDEN_GLOBALS: set[str] = {
    "os",
    "io",
    "require",
    "dofile",
    "loadfile",
    "load",
    "debug",
    "coroutine",
    "setmetatable",
    "getmetatable",
    "rawget",
    "rawset",
    "setfenv",
    "getfenv",
}

WARN_GLOBALS: set[str] = {
    "print",
    "assert",
}


def _get_line(node: Node, parent_stack: list[Node]) -> int | None:
    """Extract a best-effort line number from a node, walking up parents."""
    first_token = getattr(node, "first_token", None)
    if first_token is not None:
        return first_token.line
    for parent in reversed(parent_stack):
        first_token = getattr(parent, "first_token", None)
        if first_token is not None:
            return first_token.line
    return None


def _make_issue(
    issue_type: str,
    severity: LuaIssueSeverity,
    message: str,
    *,
    line: int | None = None,
    column: int | None = None,
) -> LuaIssue:
    return LuaIssue(
        type=issue_type,
        severity=severity,
        message=LuaIssueMessage(line=line, column=column, message=message),
    )


class LuaASTValidator(ASTRecursiveVisitor):
    def __init__(self) -> None:
        self.errors: list[LuaIssue] = []
        self.warnings: list[LuaIssue] = []
        self._parent_stack: list[Node] = []

    def visit(self, node: Node) -> None:
        if isinstance(node, Node):
            self._parent_stack.append(node)
            super().visit(node)
            self._parent_stack.pop()
        else:
            super().visit(node)

    def _parent(self) -> Node | None:
        return self._parent_stack[-2] if len(self._parent_stack) >= 2 else None

    def _line(self, node: Node) -> int | None:
        return _get_line(node, self._parent_stack)

    # -- catch-all for allowed/unknown node types --

    def enter_Node(self, node: Node) -> None:
        if type(node) not in ALLOWED_NODE_TYPES:
            self.errors.append(
                _make_issue(
                    "FORBIDDEN_CONSTRUCT",
                    LuaIssueSeverity.ERROR,
                    f"Disallowed construct: {type(node).__name__}",
                    line=self._line(node),
                )
            )

    # -- explicit forbidden constructs --

    def enter_Goto(self, node: Node) -> None:
        self.errors.append(
            _make_issue(
                "FORBIDDEN_CONSTRUCT",
                LuaIssueSeverity.ERROR,
                f"Disallowed construct: {type(node).__name__}",
                line=self._line(node),
            )
        )

    def enter_Label(self, node: Node) -> None:
        self.errors.append(
            _make_issue(
                "FORBIDDEN_CONSTRUCT",
                LuaIssueSeverity.ERROR,
                f"Disallowed construct: {type(node).__name__}",
                line=self._line(node),
            )
        )

    def enter_Attribute(self, node: Node) -> None:
        self.errors.append(
            _make_issue(
                "FORBIDDEN_CONSTRUCT",
                LuaIssueSeverity.ERROR,
                f"Disallowed construct: {type(node).__name__}",
                line=self._line(node),
            )
        )

    def _is_global_reference(self, node: Name) -> bool:
        parent = self._parent()
        if isinstance(parent, Index) and getattr(parent, "idx", None) is node:
            return False
        if isinstance(parent, Invoke) and getattr(parent, "func", None) is node:
            return False
        if parent is None:
            return True
        if (
            isinstance(parent, (Function, LocalFunction, Method))
            and getattr(parent, "name", None) is node
        ):
            return False
        if isinstance(parent, LocalAssign):
            return False
        return True

    def enter_Name(self, node: Name) -> None:
        if not self._is_global_reference(node):
            return

        name_id = node.id
        line = self._line(node)

        if name_id in FORBIDDEN_GLOBALS:
            self.errors.append(
                _make_issue(
                    "FORBIDDEN_GLOBAL",
                    LuaIssueSeverity.ERROR,
                    f"Forbidden global '{name_id}'",
                    line=line,
                )
            )
        elif name_id in WARN_GLOBALS:
            self.warnings.append(
                _make_issue(
                    "WARN_GLOBAL",
                    LuaIssueSeverity.WARNING,
                    f"Global '{name_id}' may not be available in sandbox",
                    line=line,
                )
            )
        elif name_id not in ALLOWED_GLOBALS:
            self.errors.append(
                _make_issue(
                    "UNKNOWN_GLOBAL",
                    LuaIssueSeverity.ERROR,
                    f"Unknown global '{name_id}' is not allowed in sandbox",
                    line=line,
                )
            )


def validate_ast(code: str) -> LuaCheckResult:
    errors: list[LuaIssue] = []
    warnings: list[LuaIssue] = []

    try:
        tree = lua_ast.parse(code)
    except Exception as exc:
        errors.append(
            _make_issue(
                "PARSE_ERROR",
                LuaIssueSeverity.ERROR,
                f"Failed to parse Lua: {exc}",
            )
        )
        return LuaCheckResult(
            passed=False, exit_code=2, errors=errors, warnings=warnings
        )

    validator = LuaASTValidator()
    validator.visit(tree)

    return LuaCheckResult(
        passed=not validator.errors,
        exit_code=0 if not validator.errors else 1,
        errors=validator.errors,
        warnings=validator.warnings,
    )


async def validate_lua(
    code: str, config_path: str = "resources/luacheckrc.lua"
) -> LuaCheckResult:
    luacheck_result = await run_luacheck(code, config_path)
    ast_result = validate_ast(code)

    errors = luacheck_result.errors + ast_result.errors
    warnings = luacheck_result.warnings + ast_result.warnings
    passed = luacheck_result.passed and ast_result.passed

    return LuaCheckResult(
        passed=passed,
        exit_code=0 if passed else max(luacheck_result.exit_code, ast_result.exit_code),
        errors=errors,
        warnings=warnings,
    )
