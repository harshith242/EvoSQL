"""Facts about one database: typed statements with trigger phrases (applies_to), the stored values they rely on and an
optional evidence query. check() holds every free check a new fact must pass before it may enter the memory;
merge() unites duplicates and resolves one phrase mapped to different columns."""
import re
from dataclasses import asdict, dataclass, field

from evosql.bird import execute, note_text, value_count

KINDS = ("mapping", "encoding", "constraint", "meaning", "grain", "relation")

# Case-sensitive on purpose: "from" is ordinary English, "FROM" is SQL.
SQL_PATTERN = re.compile(r"\b(SELECT|FROM|WHERE|JOIN|GROUP BY|ORDER BY|LIMIT|DISTINCT)\b|(?i:\bcount\s*\()")

# Wording that adds a boundary rule the docs' "N < 30" style ranges leave open.
BOUNDARY = re.compile(r"includ|boundary|inclusive|exclusive|strictly|at (least|most)|or (more|less|above|below)", re.I)


@dataclass
class Fact:
    id: str
    kind: str
    subject: str
    fact: str
    applies_to: list = field(default_factory=list)  # short phrases that trigger the fact
    probe: str | None = None  # read-only evidence query, never shown to the agent
    source_qids: list = field(default_factory=list)
    values: list = field(default_factory=list)  # stored values the fact relies on: [{table, column, value}]


def render(facts):
    """The knowledge section of the agent's prompt ("" when there are no facts, so the prompt equals no-memory's)."""
    if not facts:
        return ""
    lines = ["Learned database knowledge:"]
    for subject in dict.fromkeys(f.subject for f in facts):
        lines.append(subject)
        lines += [f"  - [{f.kind}] {f.fact}" for f in facts if f.subject == subject]
    return "\n".join(lines)


def phrase_in(phrase, text):
    """Whole-phrase match with word boundaries: "age" is in "patient age" but not in "average"."""
    return re.search(rf"(?<!\w){re.escape(phrase.lower().strip())}(?!\w)", text.lower()) is not None


def _fact_text(fact):
    # Identifier quotes (`aCL IgG`, "T-BIL") are style, not part of the name.
    return re.sub(r'[`"]', "", f"{fact.subject} {fact.fact}").lower()


def fact_columns(db, fact):
    """(table, column) pairs the fact is about: written as Table.Column in its subject or text."""
    text = _fact_text(fact)
    return [(t, c) for t in db.tables for c in db.columns[t] if f"{t}.{c}".lower() in text]


def fact_tables(db, fact):
    """Tables the fact names, as Table.Column or as a table name on its own."""
    text = _fact_text(fact)
    return {t for t, _ in fact_columns(db, fact)} | {t for t in db.tables if phrase_in(t, text)}


def column_note(db, table, column):
    """The column's description text ("" when undocumented)."""
    note = db.notes.get(table, {}).get(column.lower())
    return note_text(note) if note else ""


def check_fact(fact, db):
    """Why a fact must be dropped for its content (kind, phrase, SQL, column, value, scope, docs, probe), or None."""
    if fact.kind not in KINDS:
        return "unknown kind"
    if not any(isinstance(p, str) and p.strip() for p in fact.applies_to):
        return "no applies_to phrase"
    if SQL_PATTERN.search(fact.fact):
        return "contains SQL"

    table, _, col = re.sub(r'[`"]', "", fact.subject).partition(".")
    if col and table in db.tables and col not in db.columns[table]:
        return "unknown column"
    # Only the declared {table, column, value} entries are grounded; quoted words in the text are prose.
    for v in fact.values:
        if v["table"] not in db.tables or v["column"] not in db.columns[v["table"]]:
            return "unknown column"
        if not value_count(db, v["table"], v["column"], v["value"]):
            return f"value not in data: {v['value']!r}"
    if not fact_tables(db, fact):
        return "not scoped to the schema"

    if in_docs(fact, db):
        return "already in docs"
    if fact.probe is not None:
        if not re.match(r"\s*(SELECT|WITH)\b", fact.probe, re.IGNORECASE):
            return "probe is not a SELECT"
        rows, error = execute(db.path, fact.probe, max_rows=1)  # read-only, one statement, 30 s timeout
        if error:
            return f"probe failed: {error}"
        if not rows:
            return "probe returned no rows"
    return None


def check(fact, db, q, gold):
    """Why a new fact learned from question q must be dropped (content checks, then leakage of q), or None."""
    reason = check_fact(fact, db)
    if reason:
        return reason
    # A stored code in 2+ rows may equal the answer (e.g. 'DSQ'); trigger phrases may reuse the question's words.
    codes = {str(v["value"]).strip().lower() for v in fact.values
             if value_count(db, v["table"], v["column"], v["value"]) >= 2}
    texts = [(fact.subject, True), (fact.fact, True)] + [(p, False) for p in fact.applies_to]
    for text, wording in texts:
        if leak := leaks(text, q.question, q.gold_sql, gold, allowed=codes, wording=wording):
            return f"leakage: {leak}"
    return None


def _direction(text):
    # "<" or ">" when the text states one comparison direction, else None.
    less = re.search(r"\b(below|under|less|lower|smaller)\b|<", text, re.I)
    more = re.search(r"\b(above|over|greater|higher|larger|exceed\w*)\b|>", text, re.I)
    return "<" if less and not more else ">" if more and not less else None


def in_docs(fact, db):
    """True when a range or code fact only restates a named column's docs (every number, value and direction)."""
    if fact.kind not in ("constraint", "encoding") or BOUNDARY.search(fact.fact):
        return False
    tokens = re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)", fact.fact) + [str(v["value"]) for v in fact.values]
    notes = [column_note(db, t, c) for t, c in fact_columns(db, fact)]
    same_way = lambda n: _direction(fact.fact) in (None, _direction(n))  # flipping the docs' direction corrects them
    has_all = lambda n: all(re.search(rf"(?<![\w.]){re.escape(x)}(?!\w|\.\d)", n) for x in tokens)
    return bool(tokens) and any(n and same_way(n) and has_all(n) for n in notes)


def leaks(text, question, gold_sql, gold, allowed=(), wording=True):
    """Why the text memorizes this question (an answer value or copied wording) rather than knowledge, or None."""
    values = {str(v).strip().lower() for row in gold[:50] for v in row} - set(allowed)
    single_number = len(gold) == 1 and len(gold[0]) == 1 and isinstance(gold[0][0], int | float)
    for v in sorted(values):
        # Constants in the gold SQL (e.g. 'F', 1) are schema knowledge; a single numeric answer counts at any length.
        if (len(v) >= 2 or single_number) and not phrase_in(v, gold_sql) and phrase_in(v, text):
            return f"contains answer value {v!r}"
    if not wording:
        return None
    q_words, t_words = re.findall(r"\w+", question.lower()), re.findall(r"\w+", text.lower())
    q_grams = {tuple(q_words[i:i + 5]) for i in range(len(q_words) - 4)}
    if any(tuple(t_words[i:i + 5]) in q_grams for i in range(len(t_words) - 4)):
        return "copies question wording"
    return None


def fact_key(fact):
    """Facts with the same key are duplicates: same kind, subject and text (normalised)."""
    return fact.kind, _norm(fact.subject), _norm(fact.fact)


def _norm(text):
    # Quoted values stay whole: "'+'" and "'-'" differ although they have no word characters.
    return " ".join(re.findall(r"'[^']*'|\w+", re.sub(r'[`"]', "", text).lower()))


def merge(facts, db):
    """(facts, conflicts): duplicates united; a phrase mapped to 2+ columns kept by the best-supported mapping only."""
    unique = {}
    for f in facts:
        key = fact_key(f)
        if key not in unique:
            unique[key] = Fact(**asdict(f))
            continue
        old = unique[key]
        old.source_qids = sorted(set(old.source_qids) | set(f.source_qids))
        old.applies_to = list(dict.fromkeys(old.applies_to + f.applies_to))

    kept, conflicts = list(unique.values()), []
    targets = {f.id: frozenset(fact_columns(db, f)) for f in kept}
    for phrase in sorted({_norm(p) for f in kept if f.kind == "mapping" for p in f.applies_to}):
        group = [f for f in kept
                 if f.kind == "mapping" and targets[f.id] and phrase in {_norm(p) for p in f.applies_to}]
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
