"""Knowledge delivery modes: how the agent sees the fact book. Each mode gives a prompt section per question, extra
tools and answers to its own tool calls; `used` counts the knowledge the current question got."""
from evosql.agent import tool_schema
from evosql.facts import render
from evosql.search import Embedder, HybridIndex

STRUCTURE = ("grain", "relation")  # always in the retrieve prompt: they matter for counting and joins, not phrases


class NoKnowledge:
    tools = []

    def prompt(self, question):
        self.used = {"facts_in_prompt": 0}
        return ""

    def call(self, name, args):
        return None


class AllFacts(NoKnowledge):
    def __init__(self, book):
        self.book = book

    def prompt(self, question):
        self.used = {"facts_in_prompt": len(self.book.facts)}
        return self.book.render()


class Retrieve(NoKnowledge):
    def __init__(self, book, index, cap):
        self.book, self.index, self.cap = book, index, cap

    def prompt(self, question):
        hits = [f for f, _ in self.index.search(question, len(self.book.facts)) if f.kind not in STRUCTURE][:self.cap]
        facts = [f for f in self.book.facts if f in hits or f.kind in STRUCTURE]
        self.used = {"facts_in_prompt": len(facts)}
        return render(facts)


class SearchTool(NoKnowledge):
    tools = [tool_schema("search_knowledge", "Search learned facts about this database: what question phrases mean in "
                         "the data, value encodings, normal ranges, row grain and join paths.",
                         query="a phrase or column from the question")]

    def __init__(self, book, index, k):
        self.book, self.index, self.k = book, index, k

    def prompt(self, question):
        self.used = {"facts_in_prompt": 0, "search_calls": 0, "facts_returned": 0}
        if not self.book.facts:
            return ""
        subjects = ", ".join(dict.fromkeys(f.subject for f in self.book.facts))
        return f"Learned knowledge is available through the search_knowledge tool for: {subjects}."

    def call(self, name, args):
        if name != "search_knowledge":
            return None
        query = str(args.get("query") or "").strip()
        hits = self.index.search(query, self.k) if query else []
        self.used["search_calls"] += 1
        self.used["facts_returned"] += len(hits)
        if not hits:
            return "no matching knowledge"
        return "\n".join(f"- [{f.kind}] {f.subject}: {f.fact} (match: {how})" for f, how in hits)


def make_delivery(mode, book, search_cfg):
    if mode == "docs":
        return NoKnowledge()
    if mode == "all":
        return AllFacts(book)
    s = search_cfg
    index = HybridIndex(book.facts, Embedder(s["embed_model"], s["embed_url"]), s["min_cosine"])
    return Retrieve(book, index, s["retrieve_cap"]) if mode == "retrieve" else SearchTool(book, index, s["tool_k"])
