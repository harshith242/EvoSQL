"""v3 knowledge: typed facts about the database (mapping, constraint, encoding, meaning), grouped by subject.
check_fact drops facts that contain SQL, name columns or values that do not exist, or leak the answer."""
import copy
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evosql.bird import execute

KINDS = ("mapping", "constraint", "encoding", "meaning")
# Case-sensitive on purpose: "from" is ordinary English, "FROM" is SQL.
SQL_PATTERN = re.compile(r"\b(SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY|LIMIT|DISTINCT)\b|(?i:\bcount\s*\()")


def approx_tokens(text):
    return len(text) // 4 + 1


def leaks(text, question, gold_sql, gold, max_rows=50):
    """Return a reason if the text memorizes this question (its answer or wording) instead of stating knowledge."""
    text, sql = text.lower(), gold_sql.lower()
    for row in gold[:max_rows]:
        for value in row:
            v = str(value).strip().lower()
            # Constants that already appear in the gold SQL (e.g. 'F', 1) are schema knowledge, not answers.
            word = rf"(?<!\w){re.escape(v)}(?!\w)"
            if len(v) >= 2 and not re.search(word, sql) and re.search(word, text):
                return f"contains answer value {v!r}"
    if len(gold) == 1 and len(gold[0]) == 1 and isinstance(gold[0][0], int | float):
        # A single numeric answer: even a one-digit number is the answer.
        word = rf"(?<![\w.]){re.escape(str(gold[0][0]))}(?![\w.])"
        if not re.search(word, sql) and re.search(word, text):
            return f"contains answer value {str(gold[0][0])!r}"
    q_words, t_words = re.findall(r"\w+", question.lower()), re.findall(r"\w+", text)
    q_grams = {tuple(q_words[i:i + 5]) for i in range(len(q_words) - 4)}
    if any(tuple(t_words[i:i + 5]) in q_grams for i in range(len(t_words) - 4)):
        return "copies question wording"
    return None


@dataclass
class Fact:
    id: str
    kind: str
    subject: str
    fact: str
    source_qids: list = field(default_factory=list)


class FactBook:
    def __init__(self, facts=None, next_id=1):
        self.facts = facts or []
        self.next_id = next_id

    def apply(self, edits):
        """Return a copy with edits applied; edits are dicts {op, id, kind, subject, fact, qid}."""
        new = copy.deepcopy(self)
        for e in edits:
            old = next((f for f in new.facts if f.id == e.get("id")), None)
            if e["op"] == "add":
                new.facts.append(Fact(f"f{new.next_id}", e["kind"], e["subject"], e["fact"], [e.get("qid")]))
                new.next_id += 1
            elif e["op"] == "modify" and old:
                old.kind, old.subject, old.fact = e["kind"], e["subject"], e["fact"]
                old.source_qids.append(e.get("qid"))
            elif e["op"] == "delete" and old:
                new.facts.remove(old)
        return new

    def render(self):
        if not self.facts:
            return ""
        lines = ["Learned database knowledge:"]
        for subject in dict.fromkeys(f.subject for f in self.facts):
            lines.append(subject)
            lines += [f"  - [{f.kind}] {f.fact}" for f in self.facts if f.subject == subject]
        return "\n".join(lines)

    def total_tokens(self):
        return approx_tokens(self.render()) if self.facts else 0

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"next_id": self.next_id, "facts": [asdict(f) for f in self.facts]}, indent=1))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        return cls([Fact(**f) for f in data["facts"]], data["next_id"])


def columns(db, table):
    return [r[1] for r in execute(db.path, f'PRAGMA table_info("{table}")')[0]]


def _named_columns(db, text):
    """(table, column) pairs written as Table.Column in the text."""
    found = []
    for table in db.tables:
        for col in columns(db, table):
            if f"{table}.{col}".lower() in text.lower():
                found.append((table, col))
    return found


def _value_in(db, table, col, value):
    literal = "'" + value.replace("'", "''") + "'"
    rows, _ = execute(db.path, f'SELECT 1 FROM "{table}" WHERE CAST("{col}" AS TEXT) = {literal} LIMIT 1')
    return bool(rows)


def check_fact(fact, db, question=None, gold_sql=None, gold=None):
    """Return why the fact must be dropped, or None if it passes the free checks."""
    if fact.kind not in KINDS:
        return "unknown kind"
    if SQL_PATTERN.search(fact.fact):
        return "contains SQL"
    # Identifier quotes (`aCL IgG`, "T-BIL") are style, not part of the name.
    subject = re.sub(r'[`"]', "", fact.subject)
    if "." in subject and subject.split(".", 1)[0] in db.tables:
        table, col = subject.split(".", 1)
        if col not in columns(db, table):
            return "unknown column"
    named = _named_columns(db, re.sub(r'[`"]', "", f"{subject} {fact.fact}"))
    targets = named or [(t, c) for t in db.tables for c in columns(db, t)]
    # Quoted values only: an apostrophe inside a word ("patient's") is not a quote.
    for literal in re.findall(r"(?<!\w)'([^']*)'(?!\w)", fact.fact):
        if not any(_value_in(db, t, c, literal) for t, c in targets):
            return f"value not in data: {literal!r}"
    if question is not None:
        reason = leaks(fact.fact, question, gold_sql, gold)
        if reason:
            return f"leakage: {reason}"
    return None
