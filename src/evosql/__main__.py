"""CLI: python -m evosql stream | report   (settings in configs/base.yaml; data from scripts/get_v6_data.py)"""
import argparse

from dotenv import load_dotenv

from evosql.config import load_config


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config, e.g. deepseek or local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stream", help="run the streaming fact-memory experiment (resumable from cache)")
    sub.add_parser("report", help="write summary.md in the profile's results folder")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "stream":
        from evosql.stream import run
        run(cfg)
    else:
        from evosql.report import report
        report(cfg)


if __name__ == "__main__":
    main()
