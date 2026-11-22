// Plain-English explanations shown throughout the console.

export const STATUS: Record<string, { label: string; tone: string; help: string }> = {
  merged: { label: "Merged", tone: "good", help: "Built, reviewed and merged into the project's main branch. Done." },
  built: {
    label: "Built, not merged",
    tone: "info",
    help: "Claude built it and every check passed. It is on a factory branch waiting for you to merge it.",
  },
  awaiting_approval: {
    label: "Needs your approval",
    tone: "warn",
    help: "This ticket asks for a human review before the batch continues. Look at what changed, then approve.",
  },
  failed: {
    label: "Failed",
    tone: "bad",
    help: "The last run could not make this ticket pass its checks within the allowed attempts.",
  },
  not_built: { label: "Not built yet", tone: "muted", help: "No run has built this ticket yet." },
};

export const VERDICT: Record<string, { label: string; tone: string; help: string }> = {
  READY: { label: "Ready", tone: "good", help: "Passes every gate check. It can be built." },
  NEEDS_INFO: {
    label: "Needs information",
    tone: "warn",
    help: "Something is missing or unclear: placeholders, missing fields, an untestable criterion. Edit the ticket.",
  },
  DECOMPOSE: {
    label: "Too big: split it",
    tone: "bad",
    help: "The ticket is over a size limit, or mixes infrastructure with application code. Split it into smaller tickets.",
  },
  NOT_READY: { label: "Not ready", tone: "bad", help: "At least one ticket or batch rule fails, so nothing will be built." },
};

export const RUN_STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: "Running", tone: "info" },
  paused: { label: "Paused for approval", tone: "warn" },
  completed: { label: "Completed", tone: "good" },
  failed: { label: "Stopped: a ticket failed", tone: "bad" },
  error: { label: "Error", tone: "bad" },
};

/** What each part of a ticket is for. */
export const FIELD: Record<string, string> = {
  id: "A permanent name for the ticket, unique in the project. Commits and reports use it.",
  sequence: "The order the factory builds tickets in this batch. Gaps are fine.",
  title: "One outcome, in the imperative (e.g. “Build the Spell stage”).",
  description: "A short summary for people skimming the batch.",
  type: "feature, bug, refactor, chore, test or docs.",
  goal: "Why the work matters: what is wrong today (problem) and what is true when it is done (outcome).",
  scope_in: "The work this ticket includes.",
  scope_out: "Tempting nearby work that this ticket must NOT do. Keeps Claude focused.",
  affected_paths:
    "The only files and folders this ticket may change, relative to the unit's folder. Anything else Claude changes is rejected.",
  protected_paths: "Files this ticket must never touch.",
  technical: "What it is built with (stack), where it runs (target), what code it creates (interfaces) and the commands that check it.",
  commands: "Run from the unit's folder after every attempt. All must pass before the ticket is committed.",
  constraints: "Rules the change must respect, e.g. no new dependencies or no secrets in code.",
  acceptance_criteria:
    "How “done” is proven. Each criterion names a concrete result and a command that checks it. The factory runs every one.",
  verification:
    "new_test: Claude writes a test and the factory runs it. existing_test: a test that already exists. static_check: a command such as a build. manual: a person checks it at an approval pause.",
  size: "XS, S or M. Bigger tickets are refused: they fail more often and are harder to review.",
  risk: "low, medium or high. High risk, manual checks and deleting infrastructure need human approval.",
  approval: "When on, the batch pauses after this ticket so you can look at the result before it continues.",
  dependencies: "Tickets that must be done first. Earlier in this batch, or merged into main from another batch.",
  open_questions: "Must be empty: a ticket with open questions is not ready to build.",
};

export const KIND: Record<string, string> = {
  service: "A self-contained piece of the project, such as a web app, an API or a command-line tool.",
  integration: "Connects services together, for example with docker compose, and tests them end to end.",
};
