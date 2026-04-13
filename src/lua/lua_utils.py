import subprocess
import asyncio
import re
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from enum import StrEnum
import json


class LuaIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class LuaIssueMessage:
    line: int | None
    column: int | None
    message: str


@dataclass
class LuaIssue:
    type: str
    severity: LuaIssueSeverity
    message: LuaIssueMessage


@dataclass
class LuaCheckResult:
    passed: bool
    exit_code: int
    errors: list[LuaIssue]
    warnings: list[LuaIssue]


_POSITION_PATTERN = re.compile(r"^[^:]+:(\d+):(\d+):(.*)$")


def _parse_message(message: str) -> LuaIssueMessage:
    """
    Parses a message string and extracts line, column, and message information.
    """
    match = _POSITION_PATTERN.match(message)
    if match is not None:
        line = int(match.group(1))
        column = int(match.group(2))
        message = match.group(3).lstrip()
        return LuaIssueMessage(line=line, column=column, message=message)
    return LuaIssueMessage(line=None, column=None, message=message)


def _parse_failure(issue: ET.Element[str]) -> LuaIssue:
    """
    Parses a failure element and extracts issue information.
    """
    code_type = issue.get("type", "unknown")
    message = issue.get("message", "")
    issue_message = _parse_message(message)
    if code_type.startswith("E"):
        severity = LuaIssueSeverity.ERROR
    else:
        severity = LuaIssueSeverity.WARNING

    return LuaIssue(
        type=code_type,
        severity=severity,
        message=issue_message,
    )


def _parse_error(issue: ET.Element[str]) -> LuaIssue:
    code_type = issue.get("type", "unknown")
    message = issue.get("message", "")
    issue_message = _parse_message(message)
    severity = LuaIssueSeverity.ERROR

    return LuaIssue(
        type=code_type,
        severity=severity,
        message=issue_message,
    )


def _parse_luacheck_output(output: str) -> tuple[list[LuaIssue], list[LuaIssue]]:
    errors: list[LuaIssue] = []
    warnings: list[LuaIssue] = []

    root = ET.fromstring(output)
    for testcase in root.iter("testcase"):
        for failure in testcase.findall("failure"):
            if failure is None:
                continue
            error = _parse_failure(failure)
            if error.severity == LuaIssueSeverity.ERROR:
                errors.append(error)
            else:
                warnings.append(error)

        for error in testcase.findall("error"):
            if error is None:
                continue
            error = _parse_error(error)
            errors.append(error)

    return errors, warnings


async def run_luacheck(
    code: str, config_path: str = "resources/luacheckrc.lua"
) -> LuaCheckResult:
    # TODO:Handle subprocess errors and timeouts
    proc = await asyncio.create_subprocess_exec(
        "luacheck",
        "-",
        "--config",
        config_path,
        "--formatter",
        "JUnit",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(
        proc.communicate(input=code.encode()), timeout=10
    )

    errors: list[LuaIssue] = []
    warnings: list[LuaIssue] = []
    output = stdout.decode().strip()
    if output:
        errors, warnings = _parse_luacheck_output(output)

    return LuaCheckResult(
        passed=proc.returncode == 0,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        errors=errors,
        warnings=warnings,
    )


def wrap_lua_code(key: str, code: str) -> str:
    """Wraps Lua code in a JSON object with a specific key."""
    return json.dumps({key: f"lua{{{code}}}lua"})


if __name__ == "__main__":
    # Example usage
    output = """
    <testsuite name="Luacheck report" tests="1">
    <testcase name="file.lua" classname="file.lua">
        <failure type="W111" message="file.lua:21:1: setting non-standard global variable 'X'"/>
        <failure type="W113" message="file.lua:25:15: accessing undefined variable 'Y'"/>
    </testcase>
    </testsuite>
    """

    errors, warnings = _parse_luacheck_output(output)
    print("Errors:")
    for error in errors:
        print(
            f"- {error.type}: {error.message}, line {error.message.line}, column {error.message.column}"
        )

    print("\nWarnings:")
    for warning in warnings:
        print(
            f"- {warning.type}: {warning.message}, line {warning.message.line}, column {warning.message.column}"
        )
