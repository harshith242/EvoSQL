"""CLI: python -m evosql run --arm evosql --order 0 | calibrate | analyze"""
import argparse

from dotenv import load_dotenv

from evosql.stream import calibrate, load_arm, load_config, run_arm


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config (default: agent_profile), e.g. local or groq")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one or more arms over one or more question orders")
    run.add_argument("--arm", nargs="+", required=True, help="arm names, run in the given order")
    run.add_argument("--order", type=int, nargs="*", help="order seeds (default: all for learning arms, first for the rest)")
    run.add_argument("--limit", type=int, help="stop after this many questions")
    cal = sub.add_parser("calibrate", help="measure the noise flip rate p")
    cal.add_argument("--n", type=int, default=20)
    sub.add_parser("analyze", help="build charts and results/summary.md from runs/")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
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


if __name__ == "__main__":
    main()
