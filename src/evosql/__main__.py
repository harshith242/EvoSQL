"""CLI: python -m evosql partition | labels | discover | run --mode M.. --set S | gate | analyze"""
import argparse
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from evosql.config import MODES, SETS, load_config


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config (default: agent_profile), e.g. deepseek or local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("partition", help="make the discovery / gate / final question sets")
    sub.add_parser("labels", help="download the corrected gold labels (asks first)")
    sub.add_parser("discover", help="write checked, merged facts from the discovery failures")
    run = sub.add_parser("run", help="answer a question set with one or more delivery modes")
    run.add_argument("--mode", nargs="+", required=True, choices=MODES)
    run.add_argument("--set", required=True, choices=SETS)
    sub.add_parser("gate", help="one-shot gate: pick the headline mode on the gate set")
    sub.add_parser("analyze", help="write summary.md in the profile's results folder")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "partition":
        from evosql.bird import load_questions
        from evosql.files import write_atomic
        from evosql.split import make_partitions
        questions = load_questions(cfg["data_dir"], cfg["db"])
        parts = make_partitions(questions, cfg["protocol"])
        write_atomic(Path(cfg["runs_dir"]) / "partitions.json", json.dumps(parts, indent=1))
        level = {q.qid: q.difficulty for q in questions}
        for name, qids in parts.items():
            print(name, len(qids), dict(Counter(level[q] for q in qids)))
    elif args.cmd == "labels":
        from evosql.labels import download
        download(cfg["data_dir"])
    elif args.cmd == "discover":
        from evosql.learn import discover
        discover(cfg)
    elif args.cmd == "run":
        from evosql.evaluate import run_mode
        for mode in args.mode:
            if not run_mode(cfg, mode, args.set):
                return
    elif args.cmd == "gate":
        from evosql.evaluate import gate
        gate(cfg)
    elif args.cmd == "analyze":
        from evosql.evaluate import analyze
        analyze(cfg)


if __name__ == "__main__":
    main()
