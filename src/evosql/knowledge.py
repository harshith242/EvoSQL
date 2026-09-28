"""Learned notes for one database: a small list of 'when X, do Y' rules rendered into the prompt."""
import copy
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def approx_tokens(text):
    return len(text) // 4 + 1


@dataclass
class Note:
    id: str
    when: str
    text: str
    source_qid: int
    created_step: int
    credited_qids: list = field(default_factory=list)

    @property
    def tokens(self):
        return approx_tokens(f"{self.when} {self.text}")


@dataclass
class Edit:
    kind: str  # add | modify | delete
    note_id: str = None
    when: str = ""
    text: str = ""

    @property
    def tokens(self):
        return approx_tokens(f"{self.when} {self.text}")


class Knowledge:
    def __init__(self, notes=None, next_id=1):
        self.notes = notes or []
        self.next_id = next_id

    def get(self, note_id):
        return next((n for n in self.notes if n.id == note_id), None)

    def apply(self, edit, step, qid):
        """Return (new Knowledge, affected note id). The original is left unchanged."""
        new = copy.deepcopy(self)
        if edit.kind == "add":
            note = Note(f"n{new.next_id}", edit.when, edit.text, qid, step)
            new.notes.append(note)
            new.next_id += 1
            return new, note.id
        note = new.get(edit.note_id)
        if note is None:
            raise ValueError(f"unknown note id {edit.note_id!r}")
        if edit.kind == "modify":
            note.when, note.text = edit.when, edit.text
        elif edit.kind == "delete":
            new.notes.remove(note)
        else:
            raise ValueError(f"unknown edit kind {edit.kind!r}")
        return new, note.id

    def without(self, note_id):
        return Knowledge([n for n in copy.deepcopy(self.notes) if n.id != note_id], self.next_id)

    def total_tokens(self):
        return sum(n.tokens for n in self.notes)

    def render(self):
        if not self.notes:
            return ""
        lines = [f"- [{n.id}] When {n.when}: {n.text}" for n in self.notes]
        return "Learned notes for this database (apply a note when its condition matches):\n" + "\n".join(lines)

    def save(self, path, done=0):
        """Atomic save; `done` = number of stream steps these notes include, checked on resume."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"done": done, "next_id": self.next_id, "notes": [asdict(n) for n in self.notes]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        return cls([Note(**n) for n in data["notes"]], data["next_id"])
