"""Knowledge: typed facts about the database, each with trigger phrases (applies_to) and an optional evidence probe.
check_fact drops facts that contain SQL, name columns or values that do not exist, or fail their probe; leaks catches
answers; merge unites duplicates and resolves phrases mapped to different columns."""
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evosql.bird import execute, quote
from evosql.files import write_atomic

KINDS = ("mapping", "encoding", "constraint", "meaning", "grain", "relation")
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
    applies_to: list = field(default_factory=list)  # short phrases that trigger the fact
    probe: str | None = None  # read-only evidence query, never shown to the agent
    source_qids: list = field(default_factory=list)


def render(facts):
    if not facts:
        return ""
    lines = ["Learned database knowledge:"]
    for subject in dict.fromkeys(f.subject for f in facts):
        lines.append(subject)
        lines += [f"  - [{f.kind}] {f.fact}" for f in facts if f.subject == subject]
    return "\n".join(lines)


class FactBook:
    def __init__(self, facts=None):
        self.facts = facts or []

    def render(self):
        return render(self.facts)

    def total_tokens(self):
        return len(self.render()) // 4

    def digest(self):
        """Short id of the knowledge content, recorded with answers so logs never mix two versions."""
        return hashlib.sha256(json.dumps([asdict(f) for f in self.facts], sort_keys=True).encode()).hexdigest()[:12]

    def save(self, path):
        write_atomic(path, json.dumps({"facts": [asdict(f) for f in self.facts]}, indent=1))

    @classmethod
    def load(cls, path, missing_ok=False):
        if missing_ok and not Path(path).exists():
            return cls()
        return cls([Fact(**f) for f in json.loads(Path(path).read_text())["facts"]])


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
    """Return why the fact must be dropped (bad kind, no trigger phrase, SQL, unknown column or value, bad probe), or None."""
    if fact.kind not in KINDS:
        return "unknown kind"
    if not any(isinstance(p, str) and p.strip() for p in fact.applies_to):
        return "no applies_to phrase"
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
    if fact.probe is not None:
        if not re.match(r"\s*(SELECT|WITH)\b", fact.probe, re.IGNORECASE):
            return "probe is not a SELECT"
        rows, error = execute(db.path, fact.probe, max_rows=1)  # read-only, one statement, 30 s timeout
        if error:
            return f"probe failed: {error}"
        if not rows:
            return "probe returned no rows"
    return None


def _norm(text):
    return " ".join(re.findall(r"\w+", text.lower()))


def merge(facts, db):
    """Unite duplicates (same kind, subject and text); when one phrase maps to different columns, only the mapping with
    more source questions keeps the phrase (none on a tie); a fact left without phrases is dropped. Returns (facts, conflicts)."""
    unique = {}
    for f in facts:
        key = (f.kind, _norm(f.subject), _norm(f.fact))
        if key not in unique:
            unique[key] = Fact(**asdict(f))
            continue
        old = unique[key]
        old.source_qids = sorted(set(old.source_qids) | set(f.source_qids))
        old.applies_to = list(dict.fromkeys(old.applies_to + f.applies_to))
    kept, conflicts = list(unique.values()), []
    targets = {f.id: frozenset(fact_columns(db, f)) for f in kept}
    for phrase in sorted({_norm(p) for f in kept if f.kind == "mapping" for p in f.applies_to}):
        group = [f for f in kept if f.kind == "mapping" and targets[f.id]
                 and phrase in {_norm(p) for p in f.applies_to}]
        if len({targets[f.id] for f in group}) < 2:
            continue
        most = max(len(f.source_qids) for f in group)
        top = [f for f in group if len(f.source_qids) == most]
        winner = top[0] if len({targets[f.id] for f in top}) == 1 else None
        for f in group:
            if winner is None or targets[f.id] != targets[winner.id]:
                f.applies_to = [p for p in f.applies_to if _norm(p) != phrase]
        kept = [f for f in kept if f.applies_to]
        conflicts.append({"phrase": phrase, "facts": [f.id for f in group], "kept": winner and winner.id})
    return kept, conflicts
