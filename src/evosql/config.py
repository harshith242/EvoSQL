"""Settings from configs/base.yaml, with the chosen agent profile resolved into cfg["agent"]."""
from pathlib import Path

import yaml


def load_config(path="configs/base.yaml", agent=None):
    cfg = yaml.safe_load(Path(path).read_text())
    profile = cfg["agents"][agent or cfg["agent_profile"]]
    cfg.update(agent=profile, runs_dir=profile["runs_dir"], results_dir=profile["results_dir"])
    return cfg
