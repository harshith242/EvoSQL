"""CLI: python -m evosql run --arm evosql --order 0 | calibrate | analyze"""
import argparse

from dotenv import load_dotenv

from evosql.stream import calibrate, load_config, run_arm


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one arm over one or more question orders")
    run.add_argument("--arm", required=True)
    run.add_argument("--order", type=int, nargs="*", help="order seeds (default: all in config)")
    run.add_argument("--limit", type=int, help="stop after this many questions")
    cal = sub.add_parser("calibrate", help="measure the noise flip rate p")
    cal.add_argument("--n", type=int, default=20)
    sub.add_parser("analyze", help="build charts and results/summary.md from runs/")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.cmd == "run":
        for seed in args.order if args.order is not None else cfg["orders"]:
            if not run_arm(cfg, args.arm, seed, args.limit):
                break
    elif args.cmd == "calibrate":
        print(calibrate(cfg, args.n))
    elif args.cmd == "analyze":
        from evosql.analysis import analyze
        analyze(cfg)


if __name__ == "__main__":
    main()
