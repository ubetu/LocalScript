-- .luacheckrc for MWS Octapi

-- Lua 5.3 is closest available std (5.5 not supported by luacheck)
-- luacheckrc.lua
std = "none"  -- start from zero, not lua51/lua52 defaults

read_globals = {
    "wf",
    "_utils",
    -- Lua builtins available in the sandbox
    "type", "tonumber", "tostring", "pairs", "ipairs",
    "table", "string", "math", "error", "select",
    "unpack", "pcall", "xpcall",
    -- add/remove based on what Octapi actually exposes
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

