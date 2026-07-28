"""Allow running OpenCoeus as: python -m opencoeus [subcommand]."""
import sys


def main() -> int:
    # IF NO ARGS OR GUI, LAUNCH THE GUI
    if len(sys.argv) <= 1 or sys.argv[1] == "gui":
        from opencoeus.ui import main as gui_main
        return gui_main()
    # OTHERWISE, RUN THE CLI
    from opencoeus.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
