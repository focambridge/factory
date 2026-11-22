#!/usr/bin/env python3
"""Stand-in for `claude -p --output-format json`: returns a small valid project draft."""
import json, sys
prompt = sys.stdin.read()
name = [l.split(": ",1)[1] for l in prompt.splitlines() if l.startswith("Project name: ")]
name = name[0] if name else "X"
unit = """kind: service
description: A tiny Python tool.
packaging: none
defaults:
  stack:
    - {kind: language, name: python, version: ">=3.11"}
    - {kind: tool, name: pytest}
  target:
    environment: local
  commands:
    test: python -m pytest -q
"""
ticket = """schema_version: "1.2"
id: QZ-1
sequence: 1
title: Add a greet function to the tool
description: >
  Add greet(name) returning a greeting, with a unit test.
type: feature
goal:
  problem: >
    The tool cannot greet anyone yet, so users get no welcome message at all.
  outcome: >
    greet("Ann") returns "Hello, Ann!".
scope:
  in:
    - A greet function in tool/greet.py
  out:
    - Translations
  affected_paths:
    - tool/
    - tests/
technical:
  interfaces:
    - kind: function
      name: tool.greet.greet
      action: create
acceptance_criteria:
  - id: AC-1
    given: the name Ann
    when: greet("Ann") is called
    then: it returns "Hello, Ann!"
    verification:
      method: new_test
      reference: python -m pytest -q tests/test_greet.py
size:
  estimate: XS
  rationale: One function and one test.
  files_estimate: 2
risk:
  level: low
dependencies:
  blocked_by: []
open_questions: []
"""
if "a new batch of tickets" in prompt:
    t2 = ticket.replace("QZ-1", "QZ-2").replace("Add a greet function to the tool", "Add a farewell function to the tool").replace("greet", "bye")
    t2 = t2.replace("blocked_by: []", "blocked_by: [QZ-1]")
    print(json.dumps({"type": "result", "is_error": False, "result": json.dumps({"summary": "One more ticket.", "files": {"services/tool/tickets/batch-2/001-bye.yaml": t2, "project.yaml": "name: hijack"}})}))
    sys.exit(0)
revised = "Revise" in prompt and "What the person wants changed" in prompt
files = {"project.yaml": f"name: {name}\ndescription: A quiz tool.\nworkspace: ~/Workspace/{name}\nbase_branch: main\n",
         "README.md": f"# {name}\n\nRevised: {revised}\n",
         "services/tool/unit.yaml": unit,
         "services/tool/tickets/batch-1/001-greet.yaml": ticket,
         "seed/.gitignore": ".venv/\n__pycache__/\n",
         "seed/README.md": f"# {name}\n",
         "../escape.txt": "nope"}
reply = {"summary": "One small Python unit with one ticket." + (" (revised)" if "What the person wants changed" in prompt else ""), "files": files}
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Here it is:\n```json\n" + json.dumps(reply) + "\n```", "total_cost_usd": 0.12}))
