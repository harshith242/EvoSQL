"""Settings from configs/base.yaml, with the chosen agent profile resolved into cfg["agent"]."""
from pathlib import Path

import yaml

MODES = ("docs", "all", "retrieve", "tool", "hints")  # delivery modes; hints = docs plus BIRD hints (diagnostic only)
NO_FACTS = ("docs", "hints")
SETS = ("discovery", "gate", "final")
KNOWLEDGE = {"single": "knowledge_single.json", "verified": "knowledge_verified.json"}  # discovery variants


def split_arm(arm):
    """An arm is a delivery mode, with a knowledge variant for knowledge modes: "retrieve@verified" -> ("retrieve", "verified")."""
    mode, _, variant = arm.partition("@")
    return mode, variant or None


def load_config(path="configs/base.yaml", agent=None):
    cfg = yaml.safe_load(Path(path).read_text())
    profile = cfg["agents"][agent or cfg["agent_profile"]]
    cfg.update(agent=profile, runs_dir=profile["runs_dir"], results_dir=profile["results_dir"])
    for mode, variant in map(split_arm, cfg["protocol"].get("arms", [])):
        assert mode in MODES and (variant is None) == (mode in NO_FACTS) and variant in (None, *KNOWLEDGE), \
            f"bad arm {mode}@{variant}: modes {MODES}, variants {tuple(KNOWLEDGE)} (none for {NO_FACTS})"
    return cfg
