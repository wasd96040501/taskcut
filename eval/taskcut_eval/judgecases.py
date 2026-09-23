"""Labelled steps for the judge, each with the verdict a person watching would give.

A case is a conversation as ``$.session.messages()`` would hand it over, one
step the assistant is taking inside a turn, which the judge is asked about, and
the verdict: ``NEXT`` when the work moves on from a finished piece to another
there, ``SAME`` otherwise.

The cases are grouped by what they test. The group that matters most is the
one the question was changed for: the last piece of a list is finished, and
nothing follows it yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NEXT = "NEXT"
SAME = "SAME"


def person(text: str) -> dict:
    return {"role": "user", "text": text, "toolUses": []}


def ran(tool: str, text: str = "", **tool_input) -> dict:
    """An assistant message making one call, and the call's output after it."""
    return {"role": "assistant", "text": text, "toolUses": [{"tool_use_id": f"t-{tool}", "tool": tool, "input": tool_input}]}


def output(text: str = "ok") -> dict:
    return {"role": "user", "text": "", "toolUses": [], "toolResults": [{"tool_use_id": "t", "text": text, "isError": False}]}


def said(text: str) -> dict:
    return {"role": "assistant", "text": text, "toolUses": []}


def step(text: str, *calls: tuple[str, dict]) -> dict:
    return {"text": text, "calls": [{"name": name, "input": value} for name, value in calls]}


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    messages: list[dict]
    step: dict
    expect: str
    memory: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        return {"id": self.id, "messages": self.messages, "step": self.step, "memory": self.memory}


LIST = person(
    "Work through these in order, without stopping to ask me anything. Finish and check each one "
    "before you start the next.\n"
    "1. paginate() in pages.py drops the last item when the count divides evenly; fix it.\n"
    "2. Add a --json flag to the `export` command that prints the records as JSON.\n"
    "3. Rename util.slugify to util.make_slug everywhere."
)
TASK_1 = [
    ran("Edit", file_path="pages.py", old_string="range(0, n - 1, size)", new_string="range(0, n, size)"), output(),
    ran("Bash", command="python -m pytest tests/test_pages.py -q"), output("4 passed"),
]
TASK_2 = [
    ran("Edit", file_path="cli.py", old_string="@click.option('--csv'", new_string="@click.option('--json', is_flag=True)\n@click.option('--csv'"), output(),
    ran("Write", file_path="tests/test_export_json.py", content="def test_json(runner): ..."), output(),
    ran("Bash", command="python -m pytest tests/test_export_json.py -q"), output("2 passed"),
]
TASK_3 = [
    ran("Bash", command="grep -rl slugify --include=*.py . | xargs sed -i 's/slugify/make_slug/g'"), output(),
    ran("Bash", command="python -m pytest -q"), output("61 passed"),
]

ISSUES = person("Work through every issue in ISSUES.md, in order, without stopping to ask. Each has a failing test; make it pass without touching the tests.")
ISSUE_WORK = [
    ran("Edit", file_path="sqlglot/dialects/duckdb.py", old_string="exp.ArraySize", new_string="exp.ArrayLength"), output(),
    ran("Bash", command="python -m pytest tests/dialects/test_duckdb.py -q"), output("88 passed"),
]

FIX = [
    person("paginate() in pages.py drops the last item when the count divides evenly. Fix it."),
    ran("Edit", file_path="pages.py", old_string="range(0, n - 1, size)", new_string="range(0, n, size)"), output(),
    ran("Bash", command="python -m pytest tests/test_pages.py -q"), output("4 passed"),
    said("Fixed: paginate() used `n - 1` as the end of its range, so an even split lost its last page. "
         "tests/test_pages.py passes, including a new case for 10 items in pages of 5."),
]

CASES: list[Case] = [
    # -- inside one turn, a list handed over in one message --------------------
    Case("list-1-done-2-starts", "a piece done, another asked for", [LIST, *TASK_1],
         step("The off-by-one is fixed and tests/test_pages.py passes. Task 2: the --json flag.",
              ("Grep", {"pattern": "def export", "path": "cli.py"})), NEXT),
    Case("list-2-done-3-starts", "a piece done, another asked for", [LIST, *TASK_1, *TASK_2],
         step("--json works and its tests pass. Now task 3, the rename.", ("Grep", {"pattern": "slugify"})), NEXT),
    Case("list-1-done-terse", "a piece done, another asked for", [LIST, *TASK_1],
         step("Task 1 done.", ("Read", {"file_path": "cli.py"})), NEXT),
    Case("list-1-done-todo", "a piece done, another asked for", [LIST, *TASK_1],
         step("Fixed and verified.", ("TodoWrite", {"todos": [
             {"content": "Fix paginate off-by-one", "status": "completed"},
             {"content": "Add --json to export", "status": "in_progress"},
             {"content": "Rename slugify to make_slug", "status": "pending"}]})), NEXT),
    Case("issues-7-done-8-starts", "a piece done, another asked for", [ISSUES, *ISSUE_WORK],
         step("Issue 7 is fixed and test_duckdb passes. On to issue 8.", ("Read", {"file_path": "ISSUES.md"})), NEXT),
    Case("phase-done-next-phase", "a piece done, another asked for",
         [person("Move the settings from JSON to TOML: write a TOML loader, convert every config file, then delete the JSON loader."),
          ran("Write", file_path="settings/toml_loader.py", content="import tomllib ..."), output(),
          ran("Bash", command="python -m pytest tests/test_settings.py -q"), output("12 passed")],
         step("The TOML loader is written and its tests pass. Next, converting the config files.", ("Glob", {"pattern": "config/**/*.json"})), NEXT),

    # -- the last piece done: nothing follows it yet -----------------------------
    Case("list-3-done-checks-tree", "the last piece done", [LIST, *TASK_1, *TASK_2, *TASK_3],
         step("The rename is complete and the whole suite passes. That was the last of the three; checking the working tree.",
              ("Bash", {"command": "git status --short"})), SAME),
    Case("list-3-done-todo", "the last piece done", [LIST, *TASK_1, *TASK_2, *TASK_3],
         step("Task 3 done.", ("TodoWrite", {"todos": [
             {"content": "Fix paginate off-by-one", "status": "completed"},
             {"content": "Add --json to export", "status": "completed"},
             {"content": "Rename slugify to make_slug", "status": "completed"}]})), SAME),
    Case("list-3-done-final-suite", "the last piece done", [LIST, *TASK_1, *TASK_2, *TASK_3[:2]],
         step("make_slug is in place everywhere. All three tasks are done; one last full run of the suite to be sure.",
              ("Bash", {"command": "python -m pytest -q"})), SAME),
    Case("issues-last-done", "the last piece done", [ISSUES, *ISSUE_WORK],
         step("Issue 36 is fixed -- that was the last one in ISSUES.md. Running the whole suite once more.",
              ("Bash", {"command": "python -m pytest -q"})), SAME),
    Case("single-task-done-commits", "the last piece done", FIX[:-1],
         step("The fix is in and tested; committing it as asked in CLAUDE.md.",
              ("Bash", {"command": "git commit -am 'fix: paginate keeps the last page'"})), SAME,
         memory=["Commit each finished change with a conventional commit message."]),

    # -- a piece still in progress ----------------------------------------------
    Case("list-2-done-asks-before-3", "a piece in progress", [LIST, *TASK_1, *TASK_2],
         step("Task 2 is done. Before task 3, one question: should make_slug keep slugify as a deprecated alias?",
              ("TodoWrite", {"todos": [{"content": "Rename slugify to make_slug", "status": "pending"}]})), SAME),
    Case("list-1-mid-edit", "a piece in progress", [LIST, TASK_1[0], TASK_1[1]],
         step("The range end was off by one; running the tests to check the fix.", ("Bash", {"command": "python -m pytest tests/test_pages.py -q"})), SAME),
    Case("list-2-test-failed", "a piece in progress", [LIST, *TASK_1, *TASK_2[:4]],
         step("The JSON test fails: dates are not serialisable. Adding a default encoder.",
              ("Edit", {"file_path": "cli.py", "old_string": "json.dumps(rows)", "new_string": "json.dumps(rows, default=str)"})), SAME),
    Case("list-2-reading", "a piece in progress", [LIST, *TASK_1, TASK_2[0], TASK_2[1]],
         step("Let me look at how export builds its rows before writing the test.", ("Read", {"file_path": "export.py"})), SAME),
    Case("issues-mid", "a piece in progress", [ISSUES, ISSUE_WORK[0], ISSUE_WORK[1]],
         step("That fixed the first assertion; the second still fails on nested arrays.", ("Read", {"file_path": "sqlglot/generator.py"})), SAME),
]


def by_id() -> dict[str, Case]:
    return {case.id: case for case in CASES}
