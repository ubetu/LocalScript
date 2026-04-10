-- .luacheckrc for MWS Octapi

-- Lua 5.3 is closest available std (5.5 not supported by luacheck)
std = "lua53"

-- Platform globals: wf is read-only (agent reads from it),
-- _utils is read-only
read_globals = {
    wf = { other_fields = true },
    _utils = { other_fields = true },
}
-- Generated code assigns to top-level vars freely (e.g. result = ...)
allow_defined_top = true

-- Disable noise that doesn't help your agents:
ignore = {
    "212",  -- unused argument (common with _ in for loops)
    "213",  -- unused loop variable
    "611",  -- line with only whitespace
    "612",  -- trailing whitespace
    "631",  -- max line length
}

-- Or disable max line length entirely
max_line_length = false

