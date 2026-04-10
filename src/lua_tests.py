import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum

LUA_EXECUTABLE = "lua"
TEST_TIMEOUT = 10


class TestFailureKind(StrEnum):
    OUTPUT_MISMATCH = "output_mismatch"
    RUNTIME_ERROR = "runtime_error"
    LOAD_ERROR = "load_error"
    WRAPPER_ERROR = "wrapper_error"
    TIMEOUT = "timeout"


@dataclass
class TestFailure:
    test_name: str
    kind: TestFailureKind
    message: str
    expected: str | None = None
    actual: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass
class TestCase:
    name: str
    code: str  # Код который тестируем (Lua)
    context_json: str  # wf JSON 
    expected_lua: str  # Ожидаемое значение в виде Lua выражения (не JSON) 


@dataclass
class TestSuiteResult:
    total: int
    passed: int
    failed: int
    failures: list[TestFailure]


# Шаблон Lua-обёртки.
# Двойные фигурные скобки {{ }} - это Lua-скобки для литерала 
# (экранированы для Python `.format()`).
# Одиночные фигурные скобки {placeholder} - это места подстановки Python.
#
# Устройство:
# - Контекст передаётся через cjson.decode (JSON -> Lua-таблица)
# - Тестируемый код загружается как отдельный chunk с именем "@tested",
#   поэтому номера строк в ошибках соответствуют тестируемому коду
# - Ожидаемое значение — это Lua-выражение, вычисляемое через
#   load("return " .. expr), поэтому сравнение остаётся в родных для Lua
#   типах (nil, tables и т. д.) без потерь при roundtrip через JSON
# - Обратно в Python в виде JSON сериализуется только итоговый вердикт

# Эта страшная херабора запускает тесты.
# в одиночные скобки {} подставляются нужные значения в рантайме. Двойные {{ }} заменяются на одиночные { } 
# Устройство:
# - Контекст передаётся через cjson.decode (JSON -> Lua-таблица)
# - Тестируемый код загружается как отдельный чак с "@tested"
# - Ожидаемое значение загружается из lua выражения через load("return " .. expr) сравнение остаётся в родных для Lua
#   типах (nil, tables и т. д.) без потерь при roundtrip через JSON
# - Потом эта шутка выдает JSON с результатом тестирования 
LUA_TEST_WRAPPER = """\
local cjson = require("cjson")
cjson.decode_null_as_lightuserdata = false

-- Настройка контекста
local ctx = cjson.decode([==[{context_json}]==])
wf = ctx.wf or {{}}
_utils = {{
    array = {{
        new = function() return {{}} end,
        markAsArray = function(a) return a end,
    }}
}}

-- Сериализация Lua-значения в читаемую строку для отчёта о несовпадении
local function serialize(v, depth)
    depth = depth or 0
    if depth > 20 then return '"<too deep>"' end
    if v == nil then return "nil" end
    if type(v) == "string" then return cjson.encode(v) end
    if type(v) == "number" or type(v) == "boolean" then return tostring(v) end
    if type(v) ~= "table" then return tostring(v) end
    local parts = {{}}
    local n = #v
    local is_array = true
    for k, _ in pairs(v) do
        if type(k) ~= "number" or k < 1 or k > n or math.floor(k) ~= k then
            is_array = false
            break
        end
    end
    if is_array and n > 0 then
        for i = 1, n do
            parts[i] = serialize(v[i], depth + 1)
        end
        return "[" .. table.concat(parts, ", ") .. "]"
    else
        for k, val in pairs(v) do
            table.insert(parts, tostring(k) .. " = " .. serialize(val, depth + 1))
        end
        return "{{" .. table.concat(parts, ", ") .. "}}"
    end
end

-- Глубокая проверка равенства (поддерживает nil и вложенные таблицы)
local function deep_equal(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= "table" then return a == b end
    for k, v in pairs(a) do
        if not deep_equal(v, b[k]) then return false end
    end
    for k, _ in pairs(b) do
        if a[k] == nil then return false end
    end
    return true
end

-- Загружаем тестируемый код как отдельный чанк
-- Номера строк в ошибках будут относиться именно к нему
local fn, load_err = load([==[{tested_code}]==], "@tested")
if not fn then
    print(cjson.encode({{
        status = "load_error",
        message = load_err or "unknown"
    }}))
    os.exit(0)
end

-- Выполняем тестируемый код
local ok, actual = pcall(fn)
if not ok then
    print(cjson.encode({{
        status = "runtime_error",
        message = tostring(actual)
    }}))
    os.exit(0)
end

-- Вычисляем ожидаемое значение (Lua-выражение, а не JSON)
local exp_fn, exp_err = load("return " .. [==[{expected_lua}]==], "@expected")
if not exp_fn then
    print(cjson.encode({{
        status = "wrapper_error",
        message = "bad expected expression: " .. (exp_err or "unknown")
    }}))
    os.exit(0)
end

local exp_ok, expected = pcall(exp_fn)
if not exp_ok then
    print(cjson.encode({{
        status = "wrapper_error",
        message = "expected expression error: " .. tostring(expected)
    }}))
    os.exit(0)
end

-- Сравниваем фактическое и ожидаемое значения
if deep_equal(actual, expected) then
    print(cjson.encode({{ status = "pass" }}))
else
    print(cjson.encode({{
        status = "output_mismatch",
        expected = serialize(expected),
        actual = serialize(actual)
    }}))
end
"""

# Парсим ошибки типа `@tested:3: some error` или `@tested:3:10: some error`
_ERROR_LOC_COL_RE = re.compile(r"@?tested:(\d+):(\d+):\s*(.*)")
_ERROR_LOC_RE = re.compile(r"@?tested:(\d+):\s*(.*)")


def _build_wrapper(test_case: TestCase) -> str:
    return LUA_TEST_WRAPPER.format(
        context_json=test_case.context_json,
        tested_code=test_case.code,
        expected_lua=test_case.expected_lua,
    )


def _parse_error_location(message: str) -> tuple[str, int | None, int | None]:
    """Извлекает строку и столбец из Lua-ошибки, ссылающейся на chunk `@tested`.

    Возвращает `(clean_message, line, column)`.
    """
    m = _ERROR_LOC_COL_RE.search(message)
    if m:
        return m.group(3), int(m.group(1)), int(m.group(2))
    m = _ERROR_LOC_RE.search(message)
    if m:
        return m.group(2), int(m.group(1)), None
    return message, None, None


async def _run_single_test(test_case: TestCase) -> TestFailure | None:
    """Запускает один тестовый случай.

    Возвращает `None`, если тест пройден, и `TestFailure` в случае ошибки.
    """
    wrapper = _build_wrapper(test_case)

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
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.TIMEOUT,
            message=f"Test timed out after {TEST_TIMEOUT}s",
        )

    output = stdout.decode().strip()
    err_output = stderr.decode().strip()

    # Процесс Lua аварийно завершился до вывода результата
    # Например, если не установлен `cjson`
    if proc.returncode != 0 and not output:
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.WRAPPER_ERROR,
            message=err_output or f"lua exited with code {proc.returncode}",
        )

    # Разбираем JSON-вердикт, который вернула обёртка
    try:
        result = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.WRAPPER_ERROR,
            message=f"Unparseable wrapper output: {output[:500]}",
        )

    status = result.get("status")

    if status == "pass":
        return None

    if status == "load_error":
        msg, line, col = _parse_error_location(result.get("message", ""))
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.LOAD_ERROR,
            message=msg,
            line=line,
            column=col,
        )

    if status == "runtime_error":
        msg, line, col = _parse_error_location(result.get("message", ""))
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.RUNTIME_ERROR,
            message=msg,
            line=line,
            column=col,
        )

    if status == "output_mismatch":
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.OUTPUT_MISMATCH,
            message="Return value does not match expected",
            expected=result.get("expected"),
            actual=result.get("actual"),
        )

    if status == "wrapper_error":
        return TestFailure(
            test_name=test_case.name,
            kind=TestFailureKind.WRAPPER_ERROR,
            message=result.get("message", "unknown wrapper error"),
        )

    return TestFailure(
        test_name=test_case.name,
        kind=TestFailureKind.WRAPPER_ERROR,
        message=f"Unknown status from wrapper: {status}",
    )


async def run_tests(test_cases: list[TestCase]) -> TestSuiteResult:
    """Запускает все тестовые случаи параллельно и возвращает результаты."""
    results = await asyncio.gather(
        *[_run_single_test(tc) for tc in test_cases]
    )

    failures = [r for r in results if r is not None]

    return TestSuiteResult(
        total=len(test_cases),
        passed=len(test_cases) - len(failures),
        failed=len(failures),
        failures=failures,
    )


# Пример вызова тестов
# Паша, установи lua и lua-cjson (luarocks install lua-cjson), версия не важна 
# одаааа. нейрослоооооп
async def _example_test():
    cases = [
        # Тест 1: последний email (должен пройти)
        TestCase(
            name="last_email",
            code='return wf.vars.emails[#wf.vars.emails]',
            context_json='{"wf":{"vars":{"emails":["user1@example.com","user2@example.com","user3@example.com"]}}}',
            expected_lua='"user3@example.com"',
        ),
        # Тест 2: увеличение счётчика (должен пройти)
        TestCase(
            name="increment_counter",
            code="return wf.vars.try_count_n + 1",
            context_json='{"wf":{"vars":{"try_count_n":3}}}',
            expected_lua="4",
        ),
        # Тест: намеренное несовпадение (должен завершиться ошибкой)
        TestCase(
            name="deliberate_mismatch",
            code="return 42",
            context_json='{"wf":{"vars":{}}}',
            expected_lua="99",
        ),
        # Тест: синтаксическая ошибка (должен завершиться с load_error)
        TestCase(
            name="syntax_error",
            code="return if",
            context_json='{"wf":{"vars":{}}}',
            expected_lua="nil",
        ),
        # Тест: ошибка выполнения (должен завершиться с runtime_error)
        TestCase(
            name="runtime_error",
            code="return nil + 1",
            context_json='{"wf":{"vars":{}}}',
            expected_lua="nil",
        ),
        # Тест 4: преобразование ISO 8601 (должен пройти)
        TestCase(
            name="iso8601_conversion",
            code=(
                'DATUM = wf.vars.json.IDOC.ZCDF_HEAD.DATUM\n'
                'TIME = wf.vars.json.IDOC.ZCDF_HEAD.TIME\n'
                'local function safe_sub(str, start, finish)\n'
                '    local s = string.sub(str, start, math.min(finish, #str))\n'
                '    return s ~= "" and s or "00"\n'
                'end\n'
                'year = safe_sub(DATUM, 1, 4)\n'
                'month = safe_sub(DATUM, 5, 6)\n'
                'day = safe_sub(DATUM, 7, 8)\n'
                'hour = safe_sub(TIME, 1, 2)\n'
                'minute = safe_sub(TIME, 3, 4)\n'
                'second = safe_sub(TIME, 5, 6)\n'
                "iso_date = string.format(\n"
                "    '%s-%s-%sT%s:%s:%s.00000Z',\n"
                "    year, month, day,\n"
                "    hour, minute, second\n"
                ")\n"
                "return iso_date"
            ),
            context_json='{"wf":{"vars":{"json":{"IDOC":{"ZCDF_HEAD":{"DATUM":"20231015","TIME":"153000"}}}}}}',
            expected_lua='"2023-10-15T15:30:00.00000Z"',
        ),
        # Тест 8: преобразование в Unix epoch (должен пройти)
        TestCase(
            name="unix_epoch_conversion",
            code=(
                'local iso_time = wf.initVariables.recallTime\n'
                'local days_in_month = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31}\n'
                'if not iso_time or not iso_time:match("^%d%d%d%d%-%d%d%-%d%dT") then\n'
                '    return nil\n'
                'end\n'
                'local function is_leap_year(year)\n'
                '    return (year % 4 == 0 and year % 100 ~= 0) or (year % 400 == 0)\n'
                'end\n'
                'local function days_since_epoch(year, month, day)\n'
                '    local days = 0\n'
                '    for y = 1970, year - 1 do\n'
                '        days = days + (is_leap_year(y) and 366 or 365)\n'
                '    end\n'
                '    for m = 1, month - 1 do\n'
                '        days = days + days_in_month[m]\n'
                '        if m == 2 and is_leap_year(year) then\n'
                '            days = days + 1\n'
                '        end\n'
                '    end\n'
                '    days = days + (day - 1)\n'
                '    return days\n'
                'end\n'
                'local function parse_iso8601_to_epoch(iso_str)\n'
                '    if not iso_str then error("Date is nil") end\n'
                '    local year, month, day, hour, min, sec, ms, offset_sign, offset_hour, offset_min =\n'
                '        iso_str:match("(%d+)-(%d+)-(%d+)T(%d+):(%d+):(%d+)%.(%d+)([+-])(%d+):(%d+)")\n'
                '    if not year then\n'
                '        year, month, day, hour, min, sec, offset_sign, offset_hour, offset_min =\n'
                '            iso_str:match("(%d+)-(%d+)-(%d+)T(%d+):(%d+):(%d+)([+-])(%d+):(%d+)")\n'
                '        ms = 0\n'
                '    end\n'
                '    if not year then error("Cannot parse date: " .. tostring(iso_str)) end\n'
                '    year = tonumber(year); month = tonumber(month); day = tonumber(day)\n'
                '    hour = tonumber(hour); min = tonumber(min); sec = tonumber(sec)\n'
                '    ms = tonumber(ms) or 0\n'
                '    offset_hour = tonumber(offset_hour); offset_min = tonumber(offset_min)\n'
                '    local total_days = days_since_epoch(year, month, day)\n'
                '    local total_seconds = total_days * 86400 + hour * 3600 + min * 60 + sec\n'
                '    local offset_seconds = offset_hour * 3600 + offset_min * 60\n'
                '    if offset_sign == "-" then offset_seconds = -offset_seconds end\n'
                '    return total_seconds - offset_seconds\n'
                'end\n'
                'local epoch_seconds = parse_iso8601_to_epoch(iso_time)\n'
                'return epoch_seconds\n'
            ),
            context_json='{"wf":{"initVariables":{"recallTime":"2023-10-15T15:30:00+00:00"}}}',
            expected_lua="1697383800",
        ),
    ]

    result = await run_tests(cases)

    print(f"\n{'='*50}")
    print(f"Results: {result.passed}/{result.total} passed, {result.failed} failed")
    print(f"{'='*50}")
    for f in result.failures:
        print(f"\n  FAIL: {f.test_name} [{f.kind}]")
        print(f"    message: {f.message}")
        if f.line is not None:
            print(f"    line: {f.line}, col: {f.column}")
        if f.expected is not None:
            print(f"    expected: {f.expected}")
            print(f"    actual:   {f.actual}")


if __name__ == "__main__":
    asyncio.run(_example_test())
