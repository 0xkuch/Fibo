"""fibo — git blame for your promises.

    fibo                 your multiplier
    fibo PROJ-412        one task, taken apart
    fibo drift           the multiplier by quarter
    fibo doctor          integrity checks
    fibo say KEY 2d      write an estimate down before you start
    fibo demo            a demo repository, then the report
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from . import __version__, config, doctor, git, render
from .analysis import analyze
from .i18n import Lang
from .model import parse_estimate
from .pair import Keys, collect
from .sources import ledger


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fibo", description="git blame for your promises",
        epilog="commands: drift · doctor · demo [PATH] · say KEY DURATION · KEY (one task)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", help="drift | doctor | demo | say | a task key")
    p.add_argument("args", nargs="*", help=argparse.SUPPRESS)
    p.add_argument("-C", dest="path", default=".", metavar="PATH", help="run as if started in PATH")
    p.add_argument("--calendar", action="store_true", help="raw calendar time instead of working hours")
    p.add_argument("--points-as-hours", type=float, metavar="N",
                   help="convert story points at N hours each (the output will say it is your assumption)")
    p.add_argument("--whose", metavar="EMAIL", help="must be one of your own addresses; there is no other subject")
    p.add_argument("--said", metavar="DURATION", help="for `say`: the estimate")
    p.add_argument("--lang", choices=["en", "ru"], help="output language (default: from the environment)")
    p.add_argument("--no-color", action="store_true", help="no ANSI colors (NO_COLOR is respected too)")
    p.add_argument("--color", action="store_true", help="colors even when not a terminal")
    p.add_argument("--offline", action="store_true", help="trackers: use cached responses only")
    p.add_argument("--refresh", action="store_true", help="trackers: ignore the cache")
    p.add_argument("-v", "--verbose", action="store_true", help="the detailed view")
    p.add_argument("--version", action="version", version=f"fibo {__version__}")
    return p


def _console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty() and (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    if sys.platform == "win32":  # let the classic console understand ANSI
        try:
            import ctypes

            kernel = ctypes.windll.kernel32
            for handle_id in (-11, -12):
                handle, mode = kernel.GetStdHandle(handle_id), ctypes.c_uint32()
                if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                    kernel.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


NOT_HERE = {"export", "team", "predict", "forecast", "all", "everyone", "aggregate"}


def _refuse(message: str, s: render.Style) -> int:
    print(s.bad(f"{render.REFUSE}  {message}"), file=sys.stderr)
    return 2


def say(args: argparse.Namespace, root: Path, cfg: config.Config, lang: Lang, s: render.Style) -> int:
    if not args.args or not (args.said or len(args.args) > 1):
        print("usage: fibo say KEY DURATION   (e.g. fibo say PROJ-412 2d)", file=sys.stderr)
        return 2
    key = args.args[0].strip().upper()
    text = args.said or " ".join(args.args[1:])
    e = parse_estimate(text, "ledger")
    if e.is_points:
        return _refuse(lang.t("no_points"), s)
    if not e.is_duration:
        return _refuse(lang.t("no_duration", said=text), s)
    before = ledger.estimates(root).get(key)
    if before:
        return _refuse(lang.t("no_again", key=key, said=before[0].text,
                              at=f"{before[0].at:%Y-%m-%d}" if before[0].at else "?"), s)
    repo = git.open_repo(root, cfg.main_branch)
    units = collect(repo, Keys({key}), git.remotes(root) or ["origin"]).get(key, [])
    if any(u.landed for u in units):
        return _refuse(lang.t("no_closed", key=key), s)
    commits = sorted((c for u in units for c in u.commits), key=lambda c: c.at)
    if commits:
        return _refuse(lang.t("no_after_start", sha=commits[0].short, at=f"{commits[0].at:%Y-%m-%d %H:%M}"), s)
    now = datetime.now().astimezone()
    entry = ledger.append(root, key, e.text, cfg.emails[0] if cfg.emails else "", now)
    print(lang.t("say_ok", key=key, said=e.text, at=f"{now:%Y-%m-%d %H:%M}"))
    print(s.dim(lang.t("say_hash", new=(ledger.head(root) or "")[:6], prev=entry["prev"][:6])))
    return 0


def main(argv: list[str] | None = None) -> int:
    _console()
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)
    lang = Lang(args.lang)
    s = render.Style(render.color_enabled(sys.stdout, False if args.no_color else True if args.color else None))
    mode = "calendar" if args.calendar else "work"
    try:
        if args.command == "demo":
            from . import demo

            return demo.run(args, lang, s)
        if args.command == "help":
            parser.print_help()
            return 0
        try:
            root = git.toplevel(args.path)
        except git.GitError:
            print(lang.t("no_git", path=Path(args.path).resolve()), file=sys.stderr)
            return 2
        cfg = config.load(root, git.user_email(root))
        if args.whose and args.whose.strip().lower() not in cfg.emails:
            return _refuse(lang.t("no_whose", email=args.whose, emails=", ".join(cfg.emails) or "—"), s)
        if args.command == "say":
            return say(args, root, cfg, lang, s)
        a = analyze(root, cfg, mode=mode, offline=args.offline, refresh=args.refresh,
                    points_as_hours=args.points_as_hours)
        code = 0
        if args.command is None:
            out = render.report(a, lang, s, args.verbose)
        elif args.command == "drift":
            out = render.drift(a, lang, s)
        elif args.command == "doctor":
            found = doctor.check(a)
            out, code = doctor.render(a, found, lang, s), (1 if found.problems else 0)
        else:
            o = a.find(args.command)
            if o is None and args.command.lower() in NOT_HERE:
                return _refuse(lang.t("no_verb", verb=args.command), s)
            if o is None:
                print(lang.t("not_found", key=args.command), file=sys.stderr)
                return 1
            out = render.detail(a, o, lang, s)
        print(out)
        for w in a.warnings:
            print(s.dim(lang.t("warning", text=w)), file=sys.stderr)
        return code
    except config.ConfigError as exc:
        print(f"fibo: {exc}", file=sys.stderr)
        return 2
    except git.GitError as exc:
        print(f"fibo: git: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # `fibo | head` is fine
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
