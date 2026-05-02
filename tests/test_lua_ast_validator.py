import asyncio

from lua.lua_parser import validate_ast, validate_lua
from lua.lua_utils import LuaCheckResult, LuaIssue, LuaIssueMessage, LuaIssueSeverity


VALID_EXAMPLES = [
    "return wf.vars.emails[#wf.vars.emails]",
    "return wf.vars.try_count_n + 1",
    """
    result = wf.vars.RESTbody.result
    for _, filteredEntry in pairs(result) do
        for key, value in pairs(filteredEntry) do
            if key ~= "ID" and key ~= "ENTITY_ID" and key ~= "CALL" then
                filteredEntry[key] = nil
            end
        end
    end
    return result
    """,
    """
    DATUM = wf.vars.json.IDOC.ZCDF_HEAD.DATUM
    TIME = wf.vars.json.IDOC.ZCDF_HEAD.TIME
    local function safe_sub(str, start, finish)
        local s = string.sub(str, start, math.min(finish, #str))
        return s ~= "" and s or "00"
    end
    year = safe_sub(DATUM, 1, 4)
    month = safe_sub(DATUM, 5, 6)
    day = safe_sub(DATUM, 7, 8)
    hour = safe_sub(TIME, 1, 2)
    minute = safe_sub(TIME, 3, 4)
    second = safe_sub(TIME, 5, 6)
    iso_date = string.format(
        '%s-%s-%sT%s:%s:%s.00000Z',
        year, month, day,
        hour, minute, second
    )
    return iso_date
    """,
    """
    function ensureArray(t)
        if type(t) ~= "table" then
            return {t}
        end
        local isArray = true
        for k, v in pairs(t) do
            if type(k) ~= "number" or math.floor(k) ~= k then
                isArray = false
                break
            end
        end
        return isArray and t or {t}
    end
    function ensureAllItemsAreArrays(objectsArray)
        if type(objectsArray) ~= "table" then
            return objectsArray
        end
        for _, obj in ipairs(objectsArray) do
            if type(obj) == "table" and obj.items then
                obj.items = ensureArray(obj.items)
            end
        end
        return objectsArray
    end
    return ensureAllItemsAreArrays(wf.vars.json.IDOC.ZCDF_HEAD.ZCDF_PACKAGES)
    """,
    """
    local result = _utils.array.new()
    local items = wf.vars.parsedCsv
    for _, item in ipairs(items) do
        if (item.Discount ~= "" and item.Discount ~= nil) or (item.Markdown ~= "" and item.Markdown ~= nil) then
            table.insert(result, item)
        end
    end
    return result
    """,
    "local n = tonumber('5')\nreturn n * n",
    """
    local text = "2024-01-02T03:04:05"
    local year, month, day, hour, minute, second
    repeat
        year, month, day, hour, minute, second = string.match(text, "(%d+)%-(%d+)%-(%d+)T(%d+):(%d+):(%d+)")
        if year then
            break
        end
        text = text .. "Z"
    until #text > 25
    while second and #second < 2 do
        second = "0" .. second
    end
    return string.format("%s%s%s", year, month, day)
    """,
]


def _messages(issues: list[LuaIssue]) -> list[str]:
    return [issue.message.message for issue in issues]


def test_valid_octapi_code():
    for code in VALID_EXAMPLES:
        result = validate_ast(code)
        assert result.passed, _messages(result.errors)
        assert result.errors == []


def test_goto_rejected():
    result = validate_ast("::start:: goto start")
    assert not result.passed
    assert "FORBIDDEN_CONSTRUCT" in {issue.type for issue in result.errors}


def test_require_rejected():
    result = validate_ast('local json = require("json")')
    assert not result.passed
    assert any("require" in message for message in _messages(result.errors))


def test_os_rejected():
    result = validate_ast("return os.time()")
    assert not result.passed
    assert any("os" in message for message in _messages(result.errors))


def test_io_rejected():
    result = validate_ast('io.write("hello")')
    assert not result.passed
    assert any("io" in message for message in _messages(result.errors))


def test_load_rejected():
    result = validate_ast('local f = load("return 1")')
    assert not result.passed
    assert any("load" in message for message in _messages(result.errors))


def test_coroutine_rejected():
    result = validate_ast("local co = coroutine.create(function() end)")
    assert not result.passed
    assert any("coroutine" in message for message in _messages(result.errors))


def test_debug_rejected():
    result = validate_ast("debug.traceback()")
    assert not result.passed
    assert any("debug" in message for message in _messages(result.errors))


def test_print_warns():
    result = validate_ast('print("hello")')
    assert result.passed
    assert result.warnings
    assert any("print" in message for message in _messages(result.warnings))


def test_syntax_error():
    result = validate_ast("if then end end end")
    assert not result.passed
    assert result.exit_code == 2
    assert any(issue.type == "PARSE_ERROR" for issue in result.errors)


def test_empty_code():
    result = validate_ast("")
    assert result.passed


def test_comment_only():
    result = validate_ast("-- this is a comment")
    assert result.passed


def test_field_name_not_flagged():
    result = validate_ast("return wf.vars.io")
    assert result.passed
    assert result.errors == []


def test_validate_lua_merges_results(monkeypatch):
    async def fake_run_luacheck(code: str, config_path: str) -> LuaCheckResult:
        return LuaCheckResult(
            passed=True,
            exit_code=0,
            errors=[],
            warnings=[
                LuaIssue(
                    type="W000",
                    severity=LuaIssueSeverity.WARNING,
                    message=LuaIssueMessage(line=1, column=1, message="luacheck warning"),
                )
            ],
        )

    monkeypatch.setattr("lua.lua_parser.run_luacheck", fake_run_luacheck)

    result = asyncio.run(validate_lua('print("hello")'))

    assert result.passed
    assert len(result.warnings) == 2
    assert any(message == "luacheck warning" for message in _messages(result.warnings))
    assert any("print" in message for message in _messages(result.warnings))
