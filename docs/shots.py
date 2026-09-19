"""Draws every picture in the README from what the program actually prints.

The demo repository is built, the commands are run, and their output is drawn
as SVG: `docs/screens/*.svg` stand still, `docs/film/*.svg` reveal themselves
line by line and loop. Nothing here is typed in by hand, and a viewer that does
not animate SVG simply shows the finished frame.

    python docs/shots.py
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fibo import __version__, config, demo, git, render  # noqa: E402
from fibo.__main__ import main  # noqa: E402
from fibo.analysis import analyze  # noqa: E402
from fibo.pair import Keys, collect  # noqa: E402

SHOWN = "/tmp/fibo-demo"  # where `fibo demo` puts it on Linux
INK, LIME, AMBER, RED, MUT, DIM, DIM2 = "#e8e8e0", "#b5e853", "#f0c419", "#ff4d5e", "#9a9f98", "#6f7a6a", "#5a6a4a"
PANEL, BAR, EDGE, DOT = "#070907", "#050605", "#1f241f", "#2f352f"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
OWL = ["..K..........K..", "..KK........KK..", "..KLK......KLK..", "..KLLKKKKKKLLK..", ".KLLLLLLLLLLLLK.",
       ".KLKKKKLLKKKKLK.", ".KKAAAAKKAAAAKK.", ".KKAANAKKANAAKK.", ".KKAAAAKKAAAAKK.", ".KLKKKKLLKKKKLK.",
       ".KLLLLLAALLLLLK.", ".KLDLDLDLDLDLDK.", ".KLLDLDLDLDLLLK.", "..KLLLLLLLLLLK..", "...KAAKLLKAAK...",
       "...KKK....KKK..."]
COLOURS = {"K": "#050605", "L": "#b5e853", "D": "#6f9a2a", "A": "#f0c419", "N": "#050605", "W": "#e8e8e0"}
EYES = (3, 4, 5, 6, 9, 10, 11, 12)


def owl(face: str) -> list[str]:
    """The same five faces the program prints in ASCII."""
    rows = [list(r) for r in OWL]
    if face == "auditor":
        for x in EYES:
            rows[6][x] = "D"
    if face == "empty":
        for x in EYES:
            rows[6][x] = rows[7][x] = "D"
            rows[8][x] = "K"
    if face == "refuse":
        for x in EYES:
            rows[6][x] = "D"
        rows[4][6] = rows[4][9] = rows[5][7] = rows[5][8] = "K"
    if face == "doctor":
        for x in (3, 4, 5, 6):
            rows[6][x] = "D"
        for x in (9, 10, 11, 12):
            rows[5][x] = rows[9][x] = "W"
        for y, x in ((6, 8), (7, 8), (8, 8), (6, 13), (7, 13), (8, 13), (10, 13), (11, 14), (12, 14)):
            rows[y][x] = "W"
    return ["".join(r) for r in rows]


def tone(line: str) -> tuple[str, bool]:
    """The colour of one line, by the rules the landing page uses."""
    t = line.strip()
    if line.startswith("$ "):
        return INK, True
    if t.startswith(("(ò,ó)", "✗")) or "not found in your tasks" in t:
        return RED, False
    if t.startswith("(o,O)"):
        return AMBER, True
    if t.startswith(("(o,o)", "(-,-)")):
        return LIME, True
    if t in ("/)_)", '""'):
        return LIME, False
    if t.startswith(("your multiplier", "твой множитель", "said: ", "сказано: ")):
        return LIME, True
    if t.startswith(("worst case", "в худшем случае")):
        return AMBER, False
    if t.startswith(("all of it computed", "всё посчитано")):
        return INK, True
    if t.startswith("✓"):
        return LIME, False
    if t.startswith(("excluded", "исключено", "one subject", "один субъект", "by kind of work", "по типам работы",
                     "!", ".fibo/ledger", "·", "demo repository", "a demo is a demo", "next:")):
        return MUT, False
    if t.endswith(("ago", "now", "назад", "сейчас")) and "×" not in t:
        return DIM, False
    return INK, False


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Program:
    """Runs the real entry point and keeps what it printed."""

    def __init__(self, path: Path, label: str = SHOWN):
        self.path, self.label = path, label
        self.hide = [str(path), render.pretty_path(path)]

    def __call__(self, *argv: str) -> list[str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(["--no-color", "--lang", "en", "-C", str(self.path), *argv])
        text = out.getvalue() + err.getvalue()
        for real in self.hide:
            text = text.replace(real, self.label)
        lines = [l.rstrip() for l in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def session(self, *commands: str) -> list[str]:
        """`$ command`, then exactly what it printed, for each command in turn."""
        lines: list[str] = []
        for command in commands:
            lines.append(f"$ {command}")
            lines += self(*command.split()[1:])
            lines.append("")
        return lines[:-1] if lines else lines


def svg(lines: list[str], face: str, title: str, film: bool = False, seconds: float = 12.0) -> str:
    size, lead, pad = 13, 20, 18
    columns = max(52, max((len(l) for l in lines), default=40) + 3)
    w = round(columns * size * 0.602 + pad * 2)
    top = 48
    h = round(top + len(lines) * lead + pad + (lead if film else 6))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
             f'font-family="{FONT}" role="img" aria-label="{esc(title)}">',
             f'<rect width="{w}" height="{h}" fill="{PANEL}"/>',
             f'<rect width="{w}" height="30" fill="{BAR}"/><rect y="30" width="{w}" height="1" fill="{EDGE}"/>']
    parts += [f'<rect x="{14 + i * 12}" y="12" width="7" height="7" fill="{DOT}"/>' for i in range(3)]
    parts.append(f'<text x="60" y="20" font-size="11" fill="{DIM2}">{esc(title)}</text>')
    parts.append(f'<text x="{w - 14}" y="20" font-size="11" fill="{DIM2}" text-anchor="end">'
                 f'fibo {__version__}</text>')
    for y, row in enumerate(owl(face)):
        for x, ch in enumerate(row):
            if ch in COLOURS:
                parts.append(f'<rect x="{w - 48 + x * 2}" y="{44 + y * 2}" width="2" height="2" fill="{COLOURS[ch]}"/>')
    if film:
        step = seconds * 0.6 / max(1, len(lines))
        style = ["@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}", ".c{animation:blink 1s steps(1) infinite}"]
        for i in range(len(lines)):
            at = min(95.0, i * step / seconds * 100)
            style.append(f".l{i}{{animation:k{i} {seconds}s steps(1) infinite}}"
                         f"@keyframes k{i}{{0%,{at:.2f}%{{opacity:0}}{at:.2f}%,96%{{opacity:1}}"
                         f"96.01%,100%{{opacity:0}}}}")
        parts.append("<style>" + "".join(style) + "</style>")
    for i, line in enumerate(lines):
        colour, bold = tone(line)
        weight = ' font-weight="700"' if bold else ""
        klass = f' class="l{i}"' if film else ""
        parts.append(f'<text{klass} x="{pad}" y="{top + i * lead}" font-size="{size}" fill="{colour}"{weight}'
                     f' xml:space="preserve">{esc(line)}</text>')
    if film:
        y = top + len(lines) * lead
        parts.append(f'<text x="{pad}" y="{y}" font-size="{size}" fill="{MUT}">$</text>')
        parts.append(f'<rect class="c" x="{pad + 14}" y="{y - 11}" width="8" height="13" fill="{LIME}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def first_day(path: Path) -> Program:
    """A repository on its first day: one commit, no promises yet."""
    path.mkdir(parents=True, exist_ok=True)
    git_cmd = ["git", "-c", "user.email=you@example.com", "-c", "user.name=You"]
    subprocess.run(git_cmd + ["init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(git_cmd + ["symbolic-ref", "HEAD", "refs/heads/main"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# new-repo\n", encoding="utf-8")
    subprocess.run(git_cmd + ["add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(git_cmd + ["commit", "-qm", "first commit"], cwd=path, check=True, capture_output=True)
    return Program(path, "~/new-repo")


def choose(run: Program) -> tuple[str, str, str]:
    """A task worth taking apart, a task already under way, and a key nobody has used."""
    a = analyze(run.path, config.load(run.path, git.user_email(run.path)))
    task = max((o for o in a.counted if o.kind == "migration"), key=lambda o: o.ratio()).key
    units = collect(git.open_repo(run.path), Keys(), git.remotes(run.path) or ["origin"])
    begun = next(k for k, us in units.items() if not any(u.landed for u in us) and any(u.commits for u in us))
    numbers = [int(k.split("-")[1]) for k in units if k.startswith("PROJ-") and k.split("-")[1].isdigit()]
    return task, begun, f"PROJ-{max(numbers) + 40}"


def draw() -> None:
    work = Path(tempfile.mkdtemp(prefix="fibo-shots-"))
    screens, films = ROOT / "docs" / "screens", ROOT / "docs" / "film"
    screens.mkdir(parents=True, exist_ok=True)
    films.mkdir(parents=True, exist_ok=True)
    try:
        path = work / "fibo-demo"
        demo.build(path)
        run = Program(path)
        task, begun, free = choose(run)

        report = run.session("fibo")
        one = run.session(f"fibo {task}")
        drift = run.session("fibo drift")
        doctor = run.session("fibo doctor")
        russian = run.session("fibo --lang ru")
        empty = first_day(work / "new-repo").session("fibo")
        refusals = run.session(f"fibo say {free} soon", f"fibo say {begun} 2d",
                               "fibo --whose someone@else.com", f"fibo say {free} 3 points",
                               "fibo export")
        said = run.session(f"fibo say {free} 2d", f"fibo say {free} 3d")

        for name, lines, face, title in (("report", report, "report", SHOWN), ("task", one, "auditor", SHOWN),
                                         ("drift", drift, "auditor", SHOWN), ("doctor", doctor, "doctor", SHOWN),
                                         ("refusals", refusals, "refuse", SHOWN),
                                         ("empty", empty, "empty", "~/new-repo"), ("ru", russian, "report", SHOWN)):
            (screens / f"{name}.svg").write_text(svg(lines, face, title), encoding="utf-8")
        for name, lines, face, seconds in (("run", report, "report", 15.0), ("task", one, "auditor", 10.0),
                                           ("doctor", doctor, "doctor", 13.0), ("say", said, "refuse", 9.0)):
            (films / f"{name}.svg").write_text(svg(lines, face, SHOWN, film=True, seconds=seconds), encoding="utf-8")
        for folder in (screens, films):
            sizes = ", ".join(f"{p.name} {p.stat().st_size // 1024}K" for p in sorted(folder.iterdir()))
            print(f"{folder.name}: {sizes}")
    finally:
        demo._remove(work)


if __name__ == "__main__":
    draw()
