"""Integrity checks. The number is only worth something if nobody could have nudged it.

  * estimates edited after the work began (Jira, Linear, GitHub and GitLab keep
    the history; it is checked against the first commit);
  * breaks in the ledger's hash chain;
  * tasks with several estimates that disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import Analysis
from .i18n import Lang
from .model import Estimate
from .pair import Outcome
from .render import MONOCLE, Style, header, when
from .sources import ledger

TRACKERS = {"jira", "linear", "github", "gitlab"}


@dataclass
class Findings:
    edited: list[tuple[Outcome, Estimate]] = field(default_factory=list)
    conflicts: list[tuple[Outcome, Estimate]] = field(default_factory=list)
    late: list[Outcome] = field(default_factory=list)  # already excluded; listed for the record
    chain: list[tuple[int, str]] = field(default_factory=list)
    ledger_present: bool = False

    @property
    def problems(self) -> int:
        return len(self.edited) + len(self.conflicts) + len(self.chain)


def check(a: Analysis) -> Findings:
    f = Findings()
    for o in a.outcomes:
        if o.estimate is None:
            continue
        for e in o.later:
            (f.edited if o.estimate.source in TRACKERS else f.conflicts).append((o, e))
        f.conflicts += [(o, e) for e in o.conflicts]
        if o.status == "after_start":
            f.late.append(o)
    _, f.chain = ledger.read(a.root)
    f.ledger_present = (a.root / ledger.PATH).is_file()
    return f


def render(a: Analysis, f: Findings, lang: Lang, s: Style, limit: int = 20) -> str:
    lines = header(a, s, MONOCLE, s.accent) + [f"  {s.bold(lang.t('doctor_title'))}", ""]

    def section(title: str, rows: list[str], quiet: bool = False) -> None:
        if not rows:
            lines.append(f"  {s.good(lang.t('doc_ok', what=title))}")
            return
        mark = s.dim("·") if quiet else s.bad("✗")
        lines.append(f"  {mark} {title}: {len(rows)}")
        lines.extend(f"      {r}" for r in rows[:limit])
        if len(rows) > limit:
            lines.append(f"      … +{len(rows) - limit}")

    section(lang.t("doc_edited"), [
        lang.t("doc_edited_row", key=o.key, old=o.estimate.text, new=e.text, when=when(a, e.at), start=when(a, o.start))
        for o, e in f.edited])
    section(lang.t("doc_conflicts"), [
        lang.t("doc_conflict_row", key=o.key, chosen=o.estimate.text, src=o.estimate.where or o.estimate.source,
               other=e.text, osrc=e.where or e.source)
        for o, e in f.conflicts])
    if f.ledger_present:
        section(lang.t("doc_chain"), [lang.t("doc_chain_row", n=n, problem=p) for n, p in f.chain])
    else:
        lines.append(f"  {s.dim('· ' + lang.t('doc_ledger_absent'))}")
    section(lang.t("doc_late"), [
        lang.t("doc_late_row", key=o.key, said=o.estimate.text, when=when(a, o.estimate.at), start=when(a, o.start))
        for o in f.late], quiet=True)
    lines.append("")
    total = lang.t("doc_total", n=f.problems, problems=lang.word(f.problems, "problem")) if f.problems \
        else lang.t("doc_none")
    lines.append(s.bad(total) if f.problems else s.good(total))
    return "\n".join(lines)
