"""CLI: python -m evosql stream | probe | report   (settings in configs/base.yaml; data from scripts/get_ehrsql_data.py)"""
import argparse

from dotenv import load_dotenv

from evosql.config import load_config


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config, e.g. deepseek or local")
    sub = parser.add_subparsers(dest="cmd", required=True)
    stream = sub.add_parser("stream", help="run the streaming memory experiment (resumable from cache)")
    stream.add_argument("--replay-check", action="store_true", help="replay only the old arms and compare with v8")
    sub.add_parser("probe", help="answer the frozen probe set with frozen memory in 5 arms")
    sub.add_parser("report", help="write summary.md in the profile's results folder")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "stream":
        from evosql.stream import run
        run(cfg, args.replay_check)
    elif args.cmd == "probe":
        from evosql.probe import run_probe
        run_probe(cfg)
    else:
        from evosql.report import report
        report(cfg)


if __name__ == "__main__":
    main()
