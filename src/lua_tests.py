import asyncio
import json
import re
import subprocess
from dataclasses import dataclass

LUA_EXECUTABLE = "lua"
TEST_TIMEOUT = 10

# Patterns to extract line/column from Lua errors referencing the "@tested" chunk
_ERROR_LOC_COL_RE = re.compile(r"@?tested:(\d+):(\d+):\s*(.*)")
_ERROR_LOC_RE = re.compile(r"@?tested:(\d+):\s*(.*)")


@dataclass
class LuaRunResult:
    success: bool
    output: str | None = None
    error: str | None = None
    line: int | None = None
    column: int | None = None


# Lua wrapper template.
# Double braces {{ }} are literal Lua braces (escaped for Python .format()).
# Single braces {placeholder} are Python substitution points.
#
# How it works:
# - Context is passed via cjson.decode (JSON -> Lua table)
# - Tested code is loaded as a separate chunk named "@tested",
#   so error line numbers correspond to the tested code
# - Result is serialized back to JSON for Python to parse
LUA_WRAPPER = """\
local cjson = require("cjson")
cjson.decode_null_as_lightuserdata = false

-- Set up context
local ctx = cjson.decode([==[{context_json}]==])
wf = ctx.wf or {{}}
_utils = {{
    array = {{
        new = function() return {{}} end,
        markAsArray = function(a) return a end,
    }}
}}

-- Load tested code as a separate chunk
local fn, load_err = load([==[{tested_code}]==], "@tested")
if not fn then
    print(cjson.encode({{
        status = "load_error",
        message = load_err or "unknown"
    }}))
    os.exit(0)
end

-- Execute tested code
local ok, result = pcall(fn)
if not ok then
    print(cjson.encode({{
        status = "runtime_error",
        message = tostring(result)
    }}))
    os.exit(0)
end

-- Check that the code produced output
if result == nil then
    print(cjson.encode({{ status = "no_output" }}))
    os.exit(0)
end

-- Try to serialize the result to JSON to verify it's valid
local encode_ok, encoded = pcall(cjson.encode, result)
if not encode_ok then
    print(cjson.encode({{
        status = "no_output",
        message = "result is not JSON-serializable: " .. tostring(encoded)
    }}))
    os.exit(0)
end

print(cjson.encode({{ status = "pass", output = encoded }}))
"""


def _parse_error_location(message: str) -> tuple[str, int | None, int | None]:
    """Extract line and column from a Lua error referencing the `@tested` chunk.

    Returns (clean_message, line, column).
    """
    m = _ERROR_LOC_COL_RE.search(message)
    if m:
        return m.group(3), int(m.group(1)), int(m.group(2))
    m = _ERROR_LOC_RE.search(message)
    if m:
        return m.group(2), int(m.group(1)), None
    return message, None, None


async def run_lua(code: str, context_json: str) -> LuaRunResult:
    """Run Lua code with the given JSON context.

    Returns a LuaRunResult indicating whether the code ran successfully
    and produced output.
    """
    wrapper = LUA_WRAPPER.format(
        context_json=context_json,
        tested_code=code,
    )

    proc = await asyncio.create_subprocess_exec(
        LUA_EXECUTABLE,
        "-",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=wrapper.encode()),
            timeout=TEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return LuaRunResult(
            success=False,
            error=f"Timed out after {TEST_TIMEOUT}s",
        )

    output = stdout.decode().strip()
    err_output = stderr.decode().strip()

    # Lua process crashed before producing output (e.g. cjson not installed)
    if proc.returncode != 0 and not output:
        return LuaRunResult(
            success=False,
            error=err_output or f"lua exited with code {proc.returncode}",
        )

    # Parse JSON verdict from the wrapper
    try:
        result = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return LuaRunResult(
            success=False,
            error=f"Unparseable wrapper output: {output[:500]}",
        )

    status = result.get("status")

    if status == "pass":
        return LuaRunResult(success=True, output=result.get("output"))

    if status in ("load_error", "runtime_error"):
        msg, line, col = _parse_error_location(result.get("message", ""))
        return LuaRunResult(
            success=False,
            error=msg,
            line=line,
            column=col,
        )

    if status == "no_output":
        msg = result.get("message", "Code produced no output (returned nil)")
        return LuaRunResult(success=False, error=msg)

    return LuaRunResult(
        success=False,
        error=f"Unknown wrapper status: {status}",
    )
