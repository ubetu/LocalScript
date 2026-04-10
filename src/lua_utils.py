import subprocess
import asyncio
import re
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from enum import StrEnum


class LuaIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class LuaIssue:
    type: str
    severity: LuaIssueSeverity
    message: str
    line: int | None = None
    column: int | None = None


@dataclass
class LuaCheckResult:
    passed: bool
    exit_code: int
    errors: list[LuaIssue]
    warnings: list[LuaIssue]



def _parse_luacheck_output(output: str) -> tuple[list[LuaIssue], list[LuaIssue]]:
    errors: list[LuaIssue] = []
    warnings: list[LuaIssue] = []
    position_pattern = re.compile(r"^[^:]+:(\d+):(\d+):(.*)$")

    root = ET.fromstring(output)
    for testcase in root.iter("testcase"):
        for failure in testcase.findall("failure"):
            if failure is None:
                continue
            code_type = failure.get("type", "unknown")
            message = failure.get("message", "")
            line = None
            column = None
            match = position_pattern.match(message)
            if match is not None:
                line = int(match.group(1))
                column = int(match.group(2))
                message = match.group(3).lstrip()
            severity = (
                LuaIssueSeverity.ERROR
                if code_type.startswith("E")
                else LuaIssueSeverity.WARNING
            )
            if severity == LuaIssueSeverity.ERROR:
                errors.append(
                    LuaIssue(
                        type=code_type,
                        severity=severity,
                        message=message,
                        line=line,
                        column=column,
                    )
                )
            else:
                warnings.append(
                    LuaIssue(
                        type=code_type,
                        severity=severity,
                        message=message,
                        line=line,
                        column=column,
                    )
                )

        for error in testcase.findall("error"):
            if error is None:
                continue
            code_type = error.get("type", "")
            message = error.get("message", code_type)
            severity = LuaIssueSeverity.ERROR
            line = None
            column = None
            match = position_pattern.match(message)
            if match is not None:
                line = int(match.group(1))
                column = int(match.group(2))
                message = match.group(3).lstrip()
            errors.append(
                LuaIssue(
                    type=code_type,
                    severity=severity,
                    message=message,
                    line=line,
                    column=column,
                )
            )

    return errors, warnings


async def run_luacheck(code: str, config_path: str) -> LuaCheckResult:
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
        print(f"- {error.type}: {error.message}, line {error.line}, column {error.column}")

    print("\nWarnings:")
    for warning in warnings:
        print(f"- {warning.type}: {warning.message}, line {warning.line}, column {warning.column}")
