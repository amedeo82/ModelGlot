"""Print and copy a shareable local diagnostic report."""

import argparse
import json
import sys
from collections.abc import Sequence

from modelglot.runtime.diagnostics import collect_report

from .clipboard import ClipboardUnavailable, copy_text


class _Arguments(argparse.Namespace):
    disconnect_integrations: bool


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="modelglot-doctor",
        description="Print and copy ModelGlot diagnostics for a bug report.",
    )
    parser.add_argument(
        "--disconnect-integrations",
        action="store_true",
        help="Disconnect recognized ModelGlot editor/app integrations before uninstalling.",
    )
    args = _Arguments()
    parser.parse_args(argv, namespace=args)
    if args.disconnect_integrations:
        from modelglot.harnesses.integration_cleanup import (
            IntegrationCleanupError,
            disconnect_integrations,
        )

        try:
            disconnect_integrations()
        except IntegrationCleanupError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print("Disconnected recognized ModelGlot editor/app integrations.")
        return
    text = json.dumps(collect_report(), indent=2, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    try:
        copy_text(text)
    except ClipboardUnavailable:
        print("Clipboard unavailable. Copy the JSON above manually.", file=sys.stderr)
    else:
        print("ModelGlot diagnostics copied to the clipboard.", file=sys.stderr)
