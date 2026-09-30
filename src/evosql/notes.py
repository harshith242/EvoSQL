"""A short working-notes file about one database (like a CLAUDE.md), edited by a proposer after the agent's failures."""
from dataclasses import dataclass, field

from evosql.facts import leaks
from evosql.llm import extract_json
from evosql.search import examples_notes

SECTIONS = ("Joins and keys", "Time and dates", "Values and naming", "Answer shape", "Traps")

NOTES_PROMPT = """You keep a short working-notes file (like a CLAUDE.md) about ONE SQLite database for a Text2SQL agent that also sees 2 similar solved examples.
Below is a question the agent got wrong even with those examples. Write what the agent still did not know that the examples did not make clear, as conventions that hold for OTHER questions on this database: joins and keys, time and dates, values and naming, answer shape (such as yes/no form, ranking ties and which columns to return), traps.
Rules:
- One convention per bullet, about 25 words; never this question's literals or answer.
- Prefer replacing or deleting a related line over adding a near-duplicate.
- The file has at most {max_lines} lines and currently has {lines}.
- Usually 1 to 3 edits; each edit gives evidence: the part of the correct SQL it explains.
Reply with only a JSON object: {{"edits": [{{"op": "add", "section": "<one of: {sections}>", "text": "...", "evidence": "..."}}, {{"op": "replace", "line": 4, "text": "...", "evidence": "..."}}, {{"op": "delete", "line": 7, "evidence": "..."}}]}} or {{"edits": []}}.

Database schema:
{ddl}

{profile}

Current notes (lines are numbered for replace and delete):
{notes}

Failed question:
Question: {question}
Examples shown to the agent:
{examples}
Agent SQL: {agent_sql}
Correct SQL: {gold_sql}"""


@dataclass
class Notes:
    bullets: list = field(default_factory=list)  # (section, text), in insertion order within a section

    def ordered(self):
        """The bullets in the order they are shown: by section, then insertion."""
        return sorted(self.bullets, key=lambda b: SECTIONS.index(b[0]))

    def _lines(self, bullet):
        lines = []
        for section in SECTIONS:
            texts = [t for s, t in self.bullets if s == section]
            if texts:
                lines += [f"## {section}"] + [bullet(t) for t in texts]
        return lines

    def render(self):
        """The section of the agent's prompt ("" when there are no notes)."""
        if not self.bullets:
            return ""
        return "\n".join(["Working notes about this database:"] + self._lines(lambda t: f"- {t}"))

    def numbered(self):
        """The notes for the proposer: bullets numbered L1, L2, ... in shown order."""
        if not self.bullets:
            return "(empty)"
        count = iter(range(1, len(self.bullets) + 1))
        return "\n".join(["Working notes about this database:"] + self._lines(lambda t: f"L{next(count)}: {t}"))

    def line_count(self):
        return len(self.render().splitlines())

    def to_markdown(self):
        return self.render()


def validate(edit, notes, q, gold, max_words):
    """Why an edit is invalid (shape, size, evidence or leakage of q's answer), or None."""
    op = edit.get("op")
    if op not in ("add", "replace", "delete"):
        return f"unknown op {op!r}"
    if op == "add" and edit.get("section") not in SECTIONS:
        return f"unknown section {edit.get('section')!r}"
    line = edit.get("line")
    if op != "add" and not (isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= len(notes.bullets)):
        return f"no such line {line!r}"
    if not (isinstance(edit.get("evidence"), str) and edit["evidence"].strip()):
        return "no evidence"
    if op == "delete":
        return None

    text = edit.get("text")
    if not (isinstance(text, str) and text.strip()):
        return "empty text"
    if len(text.split()) > max_words:
        return f"more than {max_words} words"
    leak = leaks(text, q.question, q.gold_sql, gold)
    return f"leakage: {leak}" if leak else None


def apply(notes, edits):
    """A new Notes with the edits applied in order; line numbers refer to the notes before the batch."""
    entries = [list(b) for b in notes.ordered()]
    targets = [entries[e["line"] - 1] if e["op"] != "add" else None for e in edits]

    for edit, target in zip(edits, targets):
        if edit["op"] == "add":
            entries.append([edit["section"], edit["text"].strip()])
        elif edit["op"] == "replace":
            target[1] = edit["text"].strip()
        else:
            entries = [e for e in entries if e is not target]
    return Notes([tuple(e) for e in entries])


def propose_edits(llm, db, notes, q, shown, agent_sql, max_lines):
    """The edit dicts of the proposer's reply ([] when the reply is missing or malformed)."""
    prompt = NOTES_PROMPT.format(
        max_lines=max_lines, lines=notes.line_count(), sections=", ".join(SECTIONS), ddl=db.ddl, profile=db.profile,
        notes=notes.numbered(), question=q.question, examples=examples_notes(shown) or "(none)",
        agent_sql=agent_sql or "(none)", gold_sql=q.gold_sql)
    reply = llm.chat([{"role": "user", "content": prompt}])
    obj = extract_json(reply["content"])
    edits = obj.get("edits") if isinstance(obj, dict) else None
    return [e for e in edits if isinstance(e, dict)] if isinstance(edits, list) else []
