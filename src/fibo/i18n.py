"""Two languages, one voice. English by default, Russian when your system speaks it."""

from __future__ import annotations

import locale
import os
import sys

WORDS = {
    "en": {
        "task": ("task", "tasks"), "hour": ("hour", "hours"), "day": ("day", "days"), "week": ("week", "weeks"),
        "month": ("month", "months"), "year": ("year", "years"), "commit": ("commit", "commits"),
        "problem": ("problem", "problems"),
    },
    "ru": {
        "task": ("задача", "задачи", "задач"), "hour": ("час", "часа", "часов"), "day": ("день", "дня", "дней"),
        "week": ("неделя", "недели", "недель"), "month": ("месяц", "месяца", "месяцев"),
        "year": ("год", "года", "лет"), "commit": ("коммит", "коммита", "коммитов"),
        "problem": ("проблема", "проблемы", "проблем"),
    },
}
ONE = {"en": {"hour": "an hour", "day": "a day", "week": "a week", "month": "a month", "year": "a year"},
       "ru": {"hour": "час", "day": "день", "week": "неделя", "month": "месяц", "year": "год"}}
SMALL = {"en": "one two three four five six seven eight nine ten".split(),
         "ru": "один два три четыре пять шесть семь восемь девять десять".split()}
UNIT_WORD = {"h": "hour", "d": "day", "w": "week"}

STRINGS = {
    "en": {
        "funnel": "{tasks} · {closed} closed · {estimated} estimated · {counted} counted",
        "said": 'said "{said}"', "took": "took {took}",
        "multiplier": "your multiplier", "calendar_small": "calendar {x}", "work_small": "working hours {x}",
        "p90": "worst case (p90)", "under": "underestimated", "under_value": "{pct}% of tasks",
        "kinds": "by kind of work", "drift": "drift", "now": "now", "ago": "{x} ago",
        "excluded": "excluded: {n} {tasks} ({reasons})",
        "subject": "one subject: you — {emails}",
        "footer": "all of it computed from your history, none of it written here",
        "geomean": "geometric mean", "active": "active time", "idle": "idle",
        "idle_value": "{pct}% of the span was waiting",
        "points": "points → hours at {rate}h a point: your assumption, not a measurement",
        "few": "only {n} {tasks} so far — too few to mean much",
        "mode_calendar": "calendar time: said and took taken literally",
        "empty_title": "nothing to divide yet.",
        "empty_why": "no estimate was found that was written down before the work began.",
        "empty_where": "estimates come from:",
        "empty_tracker": "tracker    .fibo.json → jira · linear · github · gitlab",
        "empty_trailer": 'commits    "Estimate: 2d" in the first commit of a branch',
        "empty_ledger": "ledger     fibo say PROJ-412 2d   (before you start)",
        "empty_demo": "or see what it looks like: fibo demo",
        "r_after_start": "estimate after start", "r_no_branch": "no branch", "r_not_duration": "not a duration",
        "r_points": "points, not time", "r_not_yours": "not your commits",
        "s_counted": "counted", "s_open": "still open",
        "s_unestimated": "no estimate — not counted, not guessed",
        "k_bugfix": "bug fixes", "k_feature": "features", "k_refactor": "refactoring", "k_migration": "migrations",
        "k_tests": "tests", "k_docs": "docs", "k_perf": "performance", "k_infra": "infra", "k_chore": "chores",
        "k_other": "other",
        "d_said": "said", "d_started": "started", "d_landed": "landed", "d_closed": "closed", "d_span": "span",
        "d_active": "active", "d_calendar": "calendar", "d_pause": "longest pause", "d_commits": "commits",
        "d_status": "status", "d_link": "link", "d_branch": "branch", "d_later": "changed later",
        "d_first_commit": "first commit {sha}", "d_merge": "merge {sha}", "d_tracker": "from the tracker",
        "d_yours": "{n} yours", "d_clipped": "clipped to {days} days in active",
        "not_found": "{key}: not found in your tasks",
        "drift_title": "multiplier by quarter",
        "drift_empty": "not enough history for drift: it needs 90 days of counted tasks",
        "doctor_title": "doctor",
        "doc_edited": "estimates edited after the work began",
        "doc_edited_row": "{key}: {old} → {new} on {when}; work began {start}",
        "doc_conflicts": "tasks with conflicting estimates",
        "doc_conflict_row": "{key}: {chosen} ({src}) counts; also {other} ({osrc})",
        "doc_late": "estimates written after the work began (not counted)",
        "doc_late_row": "{key}: {said} written {when}; first commit {start}",
        "doc_chain": "ledger hash chain", "doc_chain_row": "line {n}: {problem}",
        "doc_ok": "✓ {what}: clean", "doc_none": "nothing to report",
        "doc_total": "{n} {problems} found", "doc_ledger_absent": "no ledger (fibo say was never used)",
        "say_ok": "said: {key} · {said} · {at}. it gets checked after the merge.",
        "say_hash": "  .fibo/ledger.jsonl +1 line · {new} ← {prev}",
        "no_verb": "✗ fibo {verb}: it predicts nothing, exports nothing, aggregates nobody.",
        "no_duration": '✗ "{said}" is not a duration. Say a number and a unit: 2d, 4h, 1w.',
        "no_points": "✗ points are not time. There is --points-as-hours=N, and the output will say the number rests on your assumption.",
        "no_after_start": "✗ written after the work began: first commit {sha} on {at}.",
        "no_again": "✗ {key} already has an estimate: {said} ({at}). An estimate is not edited — it is checked.",
        "no_closed": "✗ {key} is already done. A closed task cannot be re-estimated.",
        "no_whose": "✗ this tool has one subject. {email} is not one of your addresses ({emails}).",
        "no_git": "not a git repository: {path}",
        "demo_where": "demo repository: {path}",
        "demo_note": "a demo is a demo: reproducible, and nobody's real history. yours starts empty.",
        "demo_next": "next:  fibo -C {path} {cmd}",
        "demo_exists": "{path} exists and is not a fibo demo; pick another path",
        "warning": "! {text}",
    },
    "ru": {
        "funnel": "{tasks} · {closed} закрыто · {estimated} с оценкой · {counted} засчитано",
        "said": "сказал «{said}»", "took": "вышло {took}",
        "multiplier": "твой множитель", "calendar_small": "календарно {x}", "work_small": "в рабочих часах {x}",
        "p90": "в худшем случае (p90)", "under": "недооценил", "under_value": "{pct}% задач",
        "kinds": "по типам работы", "drift": "дрейф", "now": "сейчас", "ago": "{x} назад",
        "excluded": "исключено: {n} {tasks} ({reasons})",
        "subject": "один субъект — ты: {emails}",
        "footer": "всё посчитано из твоей истории, не написано здесь",
        "geomean": "геометрическое среднее", "active": "активное время", "idle": "лежало",
        "idle_value": "{pct}% срока задача ждала",
        "points": "points → часы по {rate}ч за point: это твоё допущение, не измерение",
        "few": "пока всего {n} {tasks} — слишком мало, чтобы что-то значить",
        "mode_calendar": "календарное время: «сказал» и «вышло» понимаются буквально",
        "empty_title": "делить пока нечего.",
        "empty_why": "не нашлось ни одной оценки, записанной до начала работы.",
        "empty_where": "откуда берутся оценки:",
        "empty_tracker": "трекер     .fibo.json → jira · linear · github · gitlab",
        "empty_trailer": "коммиты    «Estimate: 2d» в первом коммите ветки",
        "empty_ledger": "журнал     fibo say PROJ-412 2d   (до начала работы)",
        "empty_demo": "или посмотри, как это выглядит: fibo demo",
        "r_after_start": "оценка после старта", "r_no_branch": "нет ветки", "r_not_duration": "не длительность",
        "r_points": "points не время", "r_not_yours": "чужие коммиты",
        "s_counted": "засчитано", "s_open": "ещё открыта",
        "s_unestimated": "без оценки — не считается и не угадывается",
        "k_bugfix": "багфиксы", "k_feature": "фичи", "k_refactor": "рефакторинг", "k_migration": "миграции",
        "k_tests": "тесты", "k_docs": "документация", "k_perf": "производительность", "k_infra": "инфраструктура",
        "k_chore": "рутина", "k_other": "прочее",
        "d_said": "сказал", "d_started": "начал", "d_landed": "смёржено", "d_closed": "закрыто", "d_span": "span",
        "d_active": "active", "d_calendar": "календарно", "d_pause": "самая долгая пауза", "d_commits": "коммиты",
        "d_status": "статус", "d_link": "ссылка", "d_branch": "ветка", "d_later": "позже изменено",
        "d_first_commit": "первый коммит {sha}", "d_merge": "мерж {sha}", "d_tracker": "по трекеру",
        "d_yours": "твоих {n}", "d_clipped": "в active обрезана до {days} дней",
        "not_found": "{key}: среди твоих задач не найдено",
        "drift_title": "множитель по кварталам",
        "drift_empty": "для дрейфа мало истории: нужно 90 дней засчитанных задач",
        "doctor_title": "doctor",
        "doc_edited": "оценки, изменённые после начала работы",
        "doc_edited_row": "{key}: {old} → {new} в {when}; работа началась {start}",
        "doc_conflicts": "задачи с конфликтующими оценками",
        "doc_conflict_row": "{key}: считается {chosen} ({src}); есть ещё {other} ({osrc})",
        "doc_late": "оценки, написанные после начала работы (не засчитаны)",
        "doc_late_row": "{key}: {said} записано {when}; первый коммит {start}",
        "doc_chain": "хеш-цепочка журнала", "doc_chain_row": "строка {n}: {problem}",
        "doc_ok": "✓ {what}: чисто", "doc_none": "сообщить нечего",
        "doc_total": "найдено: {n} {problems}", "doc_ledger_absent": "журнала нет (fibo say не использовался)",
        "say_ok": "сказано: {key} · {said} · {at}. проверим после мержа.",
        "say_hash": "  .fibo/ledger.jsonl +1 строка · {new} ← {prev}",
        "no_verb": "✗ fibo {verb}: он ничего не предсказывает, ничего не экспортирует и никого не агрегирует.",
        "no_duration": "✗ «{said}» — не длительность. Скажи число и единицу: 2d, 4h, 1w.",
        "no_points": "✗ points — не время. Есть --points-as-hours=N, и в выводе будет написано, что цифра построена на твоём допущении.",
        "no_after_start": "✗ написано после начала работы: первый коммит {sha} от {at}.",
        "no_again": "✗ у {key} уже есть оценка: {said} ({at}). Оценку не редактируют — её проверяют.",
        "no_closed": "✗ {key} уже сделана. Закрытую задачу нельзя переоценить.",
        "no_whose": "✗ у этого инструмента один субъект. {email} нет среди твоих адресов ({emails}).",
        "no_git": "это не git-репозиторий: {path}",
        "demo_where": "демо-репозиторий: {path}",
        "demo_note": "демо есть демо: воспроизводимо и ничьей настоящей историей не является. твоя начинается пустой.",
        "demo_next": "дальше:  fibo -C {path} {cmd}",
        "demo_exists": "{path} уже существует и это не демо fibo; выбери другой путь",
        "warning": "! {text}",
    },
}


def detect() -> str:
    for var in ("FIBO_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x19:
                return "ru"
        except Exception:
            pass
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    return "ru" if code.lower().startswith(("ru", "russian")) else "en"


class Lang:
    def __init__(self, code: str | None = None):
        self.code = code if code in STRINGS else detect()

    def t(self, name: str, /, **kw: object) -> str:
        return STRINGS[self.code].get(name, STRINGS["en"][name]).format(**kw)

    def word(self, n: float, name: str) -> str:
        forms = WORDS[self.code][name]
        if self.code == "en":
            return forms[0] if n == 1 else forms[1]
        if n != int(n):
            return forms[1]
        n = int(abs(n))
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return forms[1]
        return forms[2]

    def int(self, n: int) -> str:
        text = f"{n:,}"
        return text.replace(",", " ") if self.code == "ru" else text

    def count(self, n: int, name: str) -> str:
        return f"{self.int(n)} {self.word(n, name)}"

    def reason(self, code: str) -> str:
        return self.t(f"r_{code}") if f"r_{code}" in STRINGS["en"] else code

    def kind(self, code: str) -> str:
        return self.t(f"k_{code}") if f"k_{code}" in STRINGS["en"] else code

    def ago(self, months: int) -> str:
        if months < 1:
            return self.t("now")
        name, n = ("year", round(months / 12)) if months >= 12 else ("month", months)
        if n == 1:
            return self.t("ago", x=ONE[self.code][name])
        number = SMALL[self.code][n - 1] if n <= 10 else str(n)
        return self.t("ago", x=f"{number} {self.word(n, name)}")

    def amount(self, hours: float, unit: str, day: float = 8.0, week: float = 40.0) -> str:
        """9 days · 3 weeks · 6 hours — in `unit`, moved up a unit when it gets long."""
        size = {"h": 1.0, "d": day, "w": week}
        if unit == "h" and hours >= 3 * day:
            unit = "d"
        if unit == "d" and hours / size["d"] >= 15:
            unit = "w"
        value = hours / size[unit]
        return f"{fmt(value)} {self.word(float(fmt(value)), UNIT_WORD[unit])}"

    def said(self, parts: tuple[tuple[float, str], ...], text: str) -> str:
        if len(parts) != 1 or parts[0][1] not in UNIT_WORD:
            return text
        n, unit = parts[0]
        if n == 1:
            return ONE[self.code][UNIT_WORD[unit]]
        return f"{fmt(n)} {self.word(n, UNIT_WORD[unit])}"


def fmt(x: float) -> str:
    """3.8 · 12 · 0.5 — one decimal below ten, whole numbers above."""
    if x >= 10:
        return str(round(x))
    text = f"{x:.1f}"
    return text[:-2] if text.endswith(".0") else text


def times(x: float) -> str:
    """A multiplier always keeps its decimal: 3.0×, not 3×."""
    return f"{x:.1f}×" if x < 100 else f"{x:.0f}×"


def by(x: float) -> str:
    return f"×{x:.1f}" if x < 100 else f"×{x:.0f}"
