"""Knowledge: typed facts about the database (mapping, constraint, encoding, meaning), grouped by subject.
check_fact drops facts that contain SQL or name columns or values that do not exist; leaks catches answers."""
import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evosql.bird import execute, quote
from evosql.files import write_atomic

KINDS = ("mapping", "constraint", "encoding", "meaning")
# Case-sensitive on purpose: "from" is ordinary English, "FROM" is SQL.
SQL_PATTERN = re.compile(r"\b(SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY|LIMIT|DISTINCT)\b|(?i:\bcount\s*\()")


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

    def add(self, kind, subject, fact, source_qids):
        self.facts.append(Fact(f"f{self.next_id}", kind, subject, fact, source_qids))
        self.next_id += 1

    def apply(self, edits):
        """Return a copy with edits applied; edits are dicts {op, id, kind, subject, fact, qid}."""
        new = copy.deepcopy(self)
        for e in edits:
            old = next((f for f in new.facts if f.id == e.get("id")), None)
            if e["op"] == "add":
                new.add(e["kind"], e["subject"], e["fact"], [e.get("qid")])
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
        return len(self.render()) // 4

    def digest(self):
        """Short id of the knowledge content, recorded with test answers so logs never mix two versions."""
        return hashlib.sha256(json.dumps([asdict(f) for f in self.facts], sort_keys=True).encode()).hexdigest()[:12]

    def save(self, path):
        write_atomic(path, json.dumps({"next_id": self.next_id, "facts": [asdict(f) for f in self.facts]}, indent=1))

    @classmethod
    def load(cls, path, missing_ok=False):
        if missing_ok and not Path(path).exists():
            return cls()
        data = json.loads(Path(path).read_text())
        return cls([Fact(**f) for f in data["facts"]], data["next_id"])


def _unquote(text):
    # Identifier quotes (`aCL IgG`, "T-BIL") are style, not part of the name.
    return re.sub(r'[`"]', "", text)


def fact_columns(db, fact):
    """(table, column) pairs the fact is about: written as Table.Column in its subject or text."""
    text = _unquote(f"{fact.subject} {fact.fact}").lower()
    return [(t, c) for t in db.tables for c in db.columns[t] if f"{t}.{c}".lower() in text]


def _value_in(db, table, col, value):
    literal = "'" + value.replace("'", "''") + "'"
    rows, _ = execute(db.path, f"SELECT 1 FROM {quote(table)} WHERE CAST({quote(col)} AS TEXT) = {literal} LIMIT 1")
    return bool(rows)


def check_fact(fact, db):
    """Return why the fact must be dropped (bad kind, SQL, unknown column or value), or None."""
    if fact.kind not in KINDS:
        return "unknown kind"
    if SQL_PATTERN.search(fact.fact):
        return "contains SQL"
    subject = _unquote(fact.subject)
    table, _, col = subject.partition(".")
    if col and table in db.tables and col not in db.columns[table]:
        return "unknown column"
    targets = fact_columns(db, fact) or [(t, c) for t in db.tables for c in db.columns[t]]
    # Quoted values only: an apostrophe inside a word ("patient's") is not a quote.
    for literal in re.findall(r"(?<!\w)'([^']*)'(?!\w)", fact.fact):
        if not any(_value_in(db, t, c, literal) for t, c in targets):
            return f"value not in data: {literal!r}"
    return None
