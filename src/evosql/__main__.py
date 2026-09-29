"""CLI: python -m evosql split | learn | test --arm docs evosql ungated selfcons | analyze"""
import argparse
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from evosql.config import ARMS, load_config


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config (default: agent_profile), e.g. deepseek or local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split", help="make the stratified learning/test split")
    sub.add_parser("learn", help="learn and freeze typed facts on the learning set")
    test = sub.add_parser("test", help="answer the test set with one or more arms")
    test.add_argument("--arm", nargs="+", required=True, choices=ARMS)
    sub.add_parser("analyze", help="write summary.md in the profile's results folder")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "split":
        from evosql.bird import load_questions
        from evosql.split import make_split, save_split
        questions = load_questions(cfg["data_dir"], cfg["db"])
        p = cfg["protocol"]
        split = make_split(questions, p["n_learn"], p["n_test"], p["seed"])
        save_split(Path(cfg["runs_dir"]) / "split.json", split)
        level = {q.qid: q.difficulty for q in questions}
        for half in ("learn", "test"):
            print(half, len(split[half]), dict(Counter(level[q] for q in split[half])))
    elif args.cmd == "learn":
        from evosql.learn import run_learn
        run_learn(cfg)
    elif args.cmd == "test":
        from evosql.evaluate import run_test
        for arm in sorted(args.arm, key=ARMS.index):  # selfcons needs docs and evosql first
            if not run_test(cfg, arm):
                return
    elif args.cmd == "analyze":
        from evosql.evaluate import analyze
        analyze(cfg)


if __name__ == "__main__":
    main()
