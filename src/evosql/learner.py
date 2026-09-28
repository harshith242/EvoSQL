"""Learning from mistakes: the proposer drafts one note edit, the gate decides whether to keep it.
The naive ratchet is the same Gate with every regularizer switched off (see configs/arms/ratchet.yaml)."""
import json
import re
from dataclasses import dataclass

from evosql.bird import tables_used
from evosql.knowledge import Edit

PROPOSER_PROMPT = """You maintain short notes that help a Text2SQL agent avoid mistakes on ONE SQLite database.
The agent answered a question wrong. Compare its SQL with the correct SQL and write ONE general, reusable note
that would have led to the correct SQL: about column meanings, value encodings, units, date formats, or join/filter conventions.
Never include the specific answer and never restate the question. Keep the note under 50 words.
If an existing note caused the mistake, you may modify or delete it instead.

Database schema:
{ddl}

Current notes:
{notes}

Question: {question}
Agent SQL: {wrong_sql}
Correct SQL: {gold_sql}

Reply with only JSON: {{"kind": "add" | "modify" | "delete", "note_id": "<id for modify/delete, else null>", "when": "<kind of question this applies to>", "text": "<the note>"}}"""


def propose(llm, db, question, wrong_sql, gold_sql, knowledge):
    """Ask the proposer for one edit. Returns an Edit, or None if the reply is unusable."""
    prompt = PROPOSER_PROMPT.format(
        ddl=db.ddl, notes=knowledge.render() or "(none yet)", question=question,
        wrong_sql=wrong_sql or "(no SQL submitted)", gold_sql=gold_sql,
    )
    reply = llm.chat([{"role": "user", "content": prompt}])
    match = re.search(r"\{.*\}", reply["content"] or "", re.DOTALL)
    try:
        obj = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        obj = None
    if not isinstance(obj, dict) or obj.get("kind") not in ("add", "modify", "delete"):
        return None
    edit = Edit(obj["kind"], obj.get("note_id"), str(obj.get("when") or ""), str(obj.get("text") or ""))
    if edit.kind != "delete" and not edit.text:
        return None
    return edit


def leaks(edit, question, gold_sql, gold, max_rows=50):
    """Return a reason if the note memorizes this question instead of stating general knowledge."""
    note = f"{edit.when} {edit.text}".lower()
    sql = gold_sql.lower()
    for row in gold[:max_rows]:
        for value in row:
            v = str(value).strip().lower()
            # Constants that already appear in the gold SQL (e.g. 'F', 1) are schema knowledge, not answers.
            if len(v) >= 2 and v not in sql and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", note):
                return f"contains answer value {v!r}"
    q_words, n_words = re.findall(r"\w+", question.lower()), re.findall(r"\w+", note)
    q_grams = {tuple(q_words[i:i + 5]) for i in range(len(q_words) - 4)}
    if any(tuple(n_words[i:i + 5]) in q_grams for i in range(len(n_words) - 4)):
        return "copies question wording"
    return None


@dataclass
class GateConfig:
    replay_k: int = 5
    noise_p: float = 0.0
    leakage_check: bool = True
    token_check: bool = True
    max_note_tokens: int = 80
    cap_tokens: int = 3000
    prune_every: int = 20


@dataclass
class Decision:
    knowledge: object
    accepted: bool
    reason: str
    gain: int = 0
    replay_n: int = 0


class Gate:
    def __init__(self, cfg, solve, tables, questions_by_id):
        self.cfg = cfg
        self.solve = solve  # solve(question, knowledge) -> bool (runs the agent, checks the result)
        self.tables = tables
        self.by_id = questions_by_id

    def related(self, q, seen):
        """Most recent seen questions whose gold SQL shares a table with q."""
        mine = tables_used(q.gold_sql, self.tables)
        hits = [s for s in reversed(seen) if tables_used(s.gold_sql, self.tables) & mine]
        return hits[: self.cfg.replay_k]

    def accept(self, edit, q, knowledge, seen, step, gold):
        cfg = self.cfg
        if edit.kind != "delete":
            reason = cfg.leakage_check and leaks(edit, q.question, q.gold_sql, gold)
            if reason:
                return Decision(knowledge, False, f"leakage: {reason}")
            if cfg.token_check and edit.tokens > cfg.max_note_tokens:
                return Decision(knowledge, False, "note too long")
        try:
            candidate, note_id = knowledge.apply(edit, step, q.qid)
        except ValueError as e:
            return Decision(knowledge, False, f"invalid edit: {e}")
        if cfg.cap_tokens and candidate.total_tokens() > cfg.cap_tokens:
            knowledge, _ = self.prune(knowledge)
            candidate, note_id = knowledge.apply(edit, step, q.qid)
            if candidate.total_tokens() > cfg.cap_tokens:
                return Decision(knowledge, False, "over knowledge cap")

        replay = [q] + self.related(q, seen)
        before = [self.solve(x, knowledge) for x in replay]
        after = [self.solve(x, candidate) for x in replay]
        if edit.kind != "delete" and not after[0]:
            return Decision(knowledge, False, "does not fix question", replay_n=len(replay))
        gain = sum(after) - sum(before)
        need = 0 if edit.kind == "delete" else 1 + round(cfg.noise_p * len(replay))
        if gain < need:
            return Decision(knowledge, False, f"gain {gain} below needed {need}", gain, len(replay))
        if edit.kind != "delete":
            fixed = [x.qid for x, b, a in zip(replay, before, after) if a and not b]
            candidate.get(note_id).credited_qids = fixed[:5]
        return Decision(candidate, True, "accepted", gain, len(replay))

    def prune(self, knowledge):
        """Drop notes whose removal does not hurt the questions they were credited with."""
        removed = []
        for note in list(knowledge.notes):
            qs = [self.by_id[i] for i in note.credited_qids]
            if not qs:
                continue
            without = knowledge.without(note.id)
            if sum(self.solve(x, without) for x in qs) >= sum(self.solve(x, knowledge) for x in qs):
                knowledge = without
                removed.append(note.id)
        return knowledge, removed
