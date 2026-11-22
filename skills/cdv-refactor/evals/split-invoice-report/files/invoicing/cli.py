"""Command line entry point: python3 -m invoicing.cli <file.csv> [--title TITLE]"""
import argparse
import logging
import sys

from invoicing.report import InvoiceReport


def main(argv=None):
    parser = argparse.ArgumentParser(prog="invoicing")
    parser.add_argument("path")
    parser.add_argument("--title", default="Invoice report")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s", stream=sys.stderr)
    report = InvoiceReport.from_file(args.path, title=args.title)
    sys.stdout.write(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
