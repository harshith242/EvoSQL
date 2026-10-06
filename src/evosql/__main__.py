"""CLI: python -m evosql [--config configs/arcwise.yaml] stream | report. configs/base.yaml runs EHRSQL (MIMIC-IV),
configs/arcwise.yaml runs Arcwise-Plat; data from scripts/get_ehrsql_data.py and scripts/get_arcwise_data.py."""
import argparse

from dotenv import load_dotenv

from evosql.config import load_config


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="evosql")
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--agent", help="agent profile from the config (default: deepseek)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    stream = sub.add_parser("stream", help="run the streaming memory experiment (resumable from cache)")
    stream.add_argument("--replay-check", action="store_true", help="replay only the old arms and compare with the replay reference run")
    sub.add_parser("report", help="write summary.md in the profile's results folder")
    args = parser.parse_args()

    cfg = load_config(args.config, args.agent)
    print(f"agent: {cfg['agent']['model']} -> {cfg['runs_dir']}/")
    if args.cmd == "stream":
        from evosql.stream import run
        run(cfg, args.replay_check)
    else:
        from evosql.report import report
        report(cfg)


if __name__ == "__main__":
    main()
