_PLATFORM_RULES = """\
Platform rules:
- Lua 5.3
- Scripts are embedded as lua{...}lua inside JSON strings. \
You return raw Lua code only, without the lua{...}lua wrapper.
- All declared workflow variables are in wf.vars
- Startup variables (from the variables input) are in wf.initVariables
- Do not use JsonPath. Access data directly: wf.vars.myVar
- The ONLY available _utils methods are:
  - _utils.array.new() — create a new empty array
  - _utils.array.markAsArray(arr) — mark an existing table as an array for JSON serialization
- No other _utils methods or submodules exist (no _utils.date, _utils.string, etc.). \
Do not invent _utils methods.
- To check if a value is an array (not a dict-table), inspect whether its keys \
are sequential integers (e.g. for k in pairs(t): type(k) ~= "number" means it is not an array).
- Allowed constructs: if/then/else, while/do/end, for/do/end, repeat/until
- Do not use os, io, require, loadstring, dofile, load, pcall. \
os.time() and os.date() are NOT available."""
 
_CODE_RESPONSE_FORMAT = """\
You must respond in this exact format:
 
ANALYSIS:
<Think until you understand the task and how to solve it. Write your reasoning step by step. Max 20 sentences.>
 
CODE:
```lua
<your complete code here>
```
 
Rules:
- The code MUST end with a return statement
- Write only the function body, no usage examples, no test code
- Do not wrap in lua{...}lua"""
 
 
# ──────────────────────────────────────────────
# Extract: case 1 — first request, no questions
# ──────────────────────────────────────────────
 
EXTRACT_PROMPT = """\
You are a parser. Extract structured information from a user request about a Lua script.

The user request may contain:
1. A task description in natural language (always present)
2. A JSON context with variables under wf.vars or wf.initVariables (sometimes present)
3. Existing Lua code that needs modification (sometimes present)
4. A JSON key indicating where to store the result (sometimes present)

Return:
- task: copy the task description exactly as the user wrote it, \
without the JSON context and without the code.
- code: existing Lua code the user wants to modify. Null if the user \
asks to write new code.
- possible_input: the JSON context provided by the user, if any. Null if not provided.
- json_key: the JSON key indicating where to store the result. Null if not explicitly specified. Should be only one key, not a path. (not "wf.vars.result...")

Do not solve the task. Only extract."""
 
 
# ──────────────────────────────────────────────
# Extract: case 2 — first request, after Q&A
# ──────────────────────────────────────────────
 
EXTRACT_AFTER_ASK_PROMPT = """\
You are a parser. The user was asked clarifying questions and has answered them. \
Combine the original request and the answers into a complete task description.

Return:
- task: a single clear task description that includes all relevant \
information from the conversation. Write it as if the user said it in one message.
- code: existing Lua code the user wants to modify. Null if the user \
asks to write new code.
- possible_input: the JSON context provided by the user, if any. Null if not provided.
- json_key: the JSON key indicating where to store the result. Null if not explicitly specified. Should be only ONE key, NOT a path. (NOT "wf.vars.result...")

Do not solve the task. Only extract and reformulate.

Before asking questions think about what information is missing from the original request that prevents you from writing the code.
use:
ANALYSIS:
<think step by step about what information is missing and what questions to ask to get that information>
 
Example conversation:
User: Добавь переменную с квадратом числа
AI: 1. Какого числа? 2. Предоставьте существующий код.
User: Числа 5, код: return tonumber('5')
Result task: Добавь переменную с квадратом числа 5
 
Example conversation:
User: Отфильтруй массив по полю
AI: 1. По какому полю? 2. Какое условие фильтрации?
User: По полю status, оставить только active
Result task: Отфильтруй массив, оставив только элементы со значением status равным active"""
 
 
# ──────────────────────────────────────────────
# Ask
# ──────────────────────────────────────────────
 
ASK_MISSING_PROMPT = """\
The user request is missing critical information.
 
Missing:
{missing_description}
 
Ask the user to provide the missing information.
Ask in the same language as the user's request.
Be brief and specific. Ask only about what is missing, nothing else."""
 
 
ASK_CLARIFY_PROMPT = """\
You analyze Lua script requests for completeness.
 
The user's request has a task description and a JSON context.
Check if the task is clear enough to write code.
 
Ask questions ONLY if:
- The task is ambiguous and could mean fundamentally different things
- Variable names in the task do not match variables in the context
- The expected return type is unclear (single value vs array vs table)
 
Do not ask about:
- Edge cases or error handling
- Code style or variable naming
- Performance considerations
- Specific values when the task can use a reasonable example/placeholder (e.g., \
use 5 or 10 for a number if no number is specified)

If the task can be completed with a reasonable assumption, prefer making \
that assumption over asking.
If the request is clear, return an empty list.
Most requests are self-contained. Default to asking nothing.
Ask in the same language as the user's request."""
 
 
# ──────────────────────────────────────────────
# Generate code (from scratch)
# ──────────────────────────────────────────────
 
GENERATE_CODE_PROMPT = f"""\
You are a Lua programmer.
 
{_PLATFORM_RULES}
 
{_CODE_RESPONSE_FORMAT}
 
The user message contains a task description followed by a JSON context.
 
Example:
 
Task: Из полученного списка email получи последний.
Context: {{"wf":{{"vars":{{"emails":["user1@example.com","user2@example.com","user3@example.com"]}}}}}}
 
ANALYSIS:
Get the last element of the emails array using the # length operator.
 
CODE:
```lua
return wf.vars.emails[#wf.vars.emails]
```
 
Example:
 
Task: Отфильтруй элементы из массива, чтобы включить только те, \
у которых есть значения в полях Discount или Markdown.
Context: {{"wf":{{"vars":{{"parsedCsv":[\
{{"SKU":"A001","Discount":"10%","Markdown":""}},\
{{"SKU":"A002","Discount":"","Markdown":"5%"}},\
{{"SKU":"A003","Discount":null,"Markdown":null}},\
{{"SKU":"A004","Discount":"","Markdown":""}}]}}}}}}
 
ANALYSIS:
Iterate over parsedCsv, keep items where Discount or Markdown is not \
empty and not nil. Use _utils.array.new() for the result array.
 
CODE:
```lua
local result = _utils.array.new()
local items = wf.vars.parsedCsv
for _, item in ipairs(items) do
    if (item.Discount ~= "" and item.Discount ~= nil) \
or (item.Markdown ~= "" and item.Markdown ~= nil) then
        table.insert(result, item)
    end
end
return result
```
Example:

Task: Для полученных данных очисти значения переменных ID, ENTITY_ID, CALL
Context: {{"wf":{{"vars":{{"RESTbody":{{"result":[{{"ID":123,"ENTITY_ID":456,"CALL":"x","OTHER":"v"}}]}}}}}}}}

ANALYSIS:
"Очисти значения переменных X, Y, Z" means keep only fields X, Y, Z and set all \
other fields to nil.

CODE:
```lua
local result = wf.vars.RESTbody.result
for _, item in pairs(result) do
    for key, _ in pairs(item) do
        if key ~= "ID" and key ~= "ENTITY_ID" and key ~= "CALL" then
            item[key] = nil
        end
    end
end
return result
```

Use `_utils.array.new()` when building a new array from scratch. \
Use `_utils.array.markAsArray(t)` when you need to return an existing table as an array \
(e.g. after wrapping a non-array value: `_utils.array.markAsArray({{val}}))`. \
Always use one of these when the result must be a JSON array.

YOU SHOULD NOT MODIFY THE `wf.vars` or `wf.initVariables`.
If task asks to modify the. You should instead return the new value, WITHOUT modifying the existing variables.
Example:

Task: Увеличивай значение переменной `example` на каждой итерации
Context: {{"wf":{{"vars":{{"example":3}}}}}}

ANALYSIS:
User wants to increment `example` on each iteration.
However, I should not modify `wf.vars.example` directly. Instead, return the new value as `example + 1`.

CODE:
```lua
return wf.vars.example + 1
```
"""
 
 
# ──────────────────────────────────────────────
# Modify code (edit existing)
# ──────────────────────────────────────────────
 
MODIFY_CODE_PROMPT = f"""\
You are a Lua programmer.
 
{_PLATFORM_RULES}
 
The user message contains a task, a JSON context, and existing code to modify.
Preserve the existing logic. Add or change only what is requested.
Do not rewrite or restructure working parts of the code.
Return the COMPLETE modified code, not just the changes.
 
{_CODE_RESPONSE_FORMAT}"""
 
 
# ──────────────────────────────────────────────
# Fix code (after validation failure)
# ──────────────────────────────────────────────
 
REVIEW_CODE_PROMPT = """\
You are a Lua code reviewer. Your job is to check whether the code correctly \
solves the given task.

You will receive:
- The task description
- The possible input (JSON context)
- The generated Lua code
- The output produced by running the code with the given input (if available)

The code should follow the platform rules and solve the task as specified.
PLATFORM RULES:
{_PLATFORM_RULES}

Think step by step before making your judgment:
Step 1. Restate what the task is asking for in one sentence.
Step 2. Read through the code line by line and describe what it actually does.
Step 3. Compare the actual output with what the task requires.
Step 4. Identify any discrepancy between what the task asks and what the code produces.
Step 5. Think whether you overcomplicate the thinking process. If the task is simple and the code is straightforward, maybe it is correct after all. 

It's OK, when we return, instead of modifying global variables, as it is forbidden to modify wf.vars. The code should return the new value instead.

If the code correctly solves the task, set is_correct to true and concerns to null.
If the code does NOT correctly solve the task, set is_correct to false and \
describe the specific problem in concerns. Be concrete: say what the code does \
wrong and what it should do instead. Cite the exact lines of code that are problematic. If there are multiple issues, list them all. \
Say where in the line does the problem occur (e.g. "in the condition of the if statement", "when accessing the variable X", "when returning the result", etc.).

Also check specifically for the array misuse issue,
Advice to use _utils.array.new() and _utils.array.markAsArray() when the something should be an array,


Do NOT report:
- Style issues, variable naming, or formatting
- Edge cases not covered by the provided input
- Performance concerns
- Static analysis issues (those are checked separately)

Focus ONLY on whether the code produces the correct result for the given task."""


FIX_CODE_PROMPT = f"""\
You are a Lua programmer.
 
{_PLATFORM_RULES}
 
The user message contains a task, a JSON context, your previous code, \
and error details.
Fix only the reported errors.
Change as little as possible. Do not rewrite the entire code.
 
{_CODE_RESPONSE_FORMAT}
addtitionally in thinking process you should printout promblems and code snippets, bade code snippets and fiexed code snippets for each problem.
You should not fix problems that are not reported by the reviewer."""