-- MWS Octapi sandbox luacheck config
std = "none"

read_globals = {
    "wf",
    "_utils",
    "type", "tonumber", "tostring",
    "pairs", "ipairs", "next",
    "table", "string", "math",
    "error", "select", "unpack",
    "pcall", "xpcall", "rawequal",
}

allow_defined_top = true

ignore = {
    "211",  -- unused local variable
    "212",  -- unused argument (common with _ in for loops)
    "213",  -- unused loop variable
    "4",    -- shadowing (upvalue/local/argument shadowing is stylistic)
    "6",    -- whitespace and formatting issues
}

max_line_length = 200
