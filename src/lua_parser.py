from dataclasses import dataclass
from luaparser import ast
from luaparser.astnodes import *


ALLOWED_STATEMENTS = {
    If, ElseIf, While, Fornum, Forin, Repeat,
    Block, Chunk, Assign, LocalAssign, Return,
    Do, Break,
    Function, LocalFunction, Call, Invoke,
}

ALLOWED_EXPRESSIONS = {
    Number, String, TrueExpr, FalseExpr, Nil,
    AddOp, SubOp, MultOp, FloatDivOp, ModOp, Concat,
    LessThanOp, GreaterThanOp, LessOrEqThanOp, GreaterOrEqThanOp,
    EqToOp, NotEqToOp, AndLoOp, OrLoOp, ULNotOp, UMinusOp, ULengthOP,
    Name, Index, Field, Table,
    AnonymousFunction,
}

FORBIDDEN_GLOBALS = {"os", "io", "require", "dofile", "loadfile", "load",
                     "coroutine", "debug", "setmetatable", "getmetatable",
                     "rawget", "rawset", "setfenv", "getfenv"}


@dataclass 
class ParserIssue:
    message: str
    line: int 
    node: str | None = None


class LuaOctapiValidator(ast.ASTVisitor):
    def __init__(self):
        self.issues: list[ParserIssue] = []

    def generic_visit(self, node):
        node_type = type(node)
        if node_type in ALLOWED_STATEMENTS or node_type in ALLOWED_EXPRESSIONS:
            self.issues.append(ParserIssue("Disallowed construct", node.line, node_type.__name__))

    def visit_Name(self, node):
        if node.id in FORBIDDEN_GLOBALS:
            self.issues.append(ParserIssue(f"Use of forbidden global '{node.id}'", node.line, "Name"))
        
    def visit_Goto(self, node):
        self.issues.append(ParserIssue("Goto statements are not allowed", node.line, "Goto"))
        
    def vist_Label(self, node):
        self.issues.append(ParserIssue("Labels are not allowed", node.line, "Label"))