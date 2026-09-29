"""CLI: python -m evosql run --arm evosql --order 0 | calibrate | analyze"""
import argparse

from dotenv import load_dotenv

from evosql.stream import calibrate, load_arm, load_config, run_arm


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config (default: agent_profile), e.g. deepseek or local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one or more arms over one or more question orders")
    run.add_argument("--arm", nargs="+", required=True, help="arm names, run in the given order")
    run.add_argument("--order", type=int, nargs="*", help="order seeds (default: all for learning arms, first for the rest)")
    run.add_argument("--limit", type=int, help="stop after this many questions")
    cal = sub.add_parser("calibrate", help="measure the noise flip rate p")
    cal.add_argument("--n", type=int, default=20)
    sub.add_parser("analyze", help="build charts and results/summary.md from runs/")
    sub.add_parser("split", help="v3: make the 50/50 learning/test split")
    sub.add_parser("learn", help="v3: learn and freeze typed facts on the learning set")
    args = parser.parse_args()

    # v3 commands default to the v3 agent profile (thinking off + value profile).
    v3 = args.cmd in ("split", "learn")
    cfg = load_config(args.config, args.agent or ("deepseek_v3" if v3 else None))
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "run":
        for arm in args.arm:
            # Non-learning arms give the same answer per question in any order, so one order is enough.
            learning = load_arm(arm, cfg["arms_dir"]).get("learning", False)
            seeds = args.order if args.order is not None else (cfg["orders"] if learning else cfg["orders"][:1])
            for seed in seeds:
                if not run_arm(cfg, arm, seed, args.limit):
                    return
    elif args.cmd == "calibrate":
        print(calibrate(cfg, args.n))
    elif args.cmd == "analyze":
        from evosql.analysis import analyze
        analyze(cfg)
    elif args.cmd == "split":
        from collections import Counter
        from pathlib import Path
        from evosql.bird import load_questions
        from evosql.split import make_split, save_split
        questions = load_questions(cfg["data_dir"], cfg["db"])
        split = make_split(questions, cfg["v3"]["n_learn"], cfg["v3"]["n_test"], cfg["v3"]["seed"])
        save_split(Path(cfg["runs_dir"]) / "split.json", split)
        level = {q.qid: q.difficulty for q in questions}
        for half in ("learn", "test"):
            print(half, len(split[half]), dict(Counter(level[q] for q in split[half])))
    elif args.cmd == "learn":
        from evosql.learn import run_learn
        run_learn(cfg)


if __name__ == "__main__":
    main()
