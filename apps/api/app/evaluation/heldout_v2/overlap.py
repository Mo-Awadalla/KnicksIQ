"""Mechanical overlap report for held-out v2 against the two existing evaluation files.

The report contains counts, ids and entity sets only. It never prints a held-out question or
answer, so the untouched-set embargo is preserved while the coverage claim stays auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .facts import dsn, load_archive

HERE = Path(__file__).resolve().parent
EVALUATION = HERE.parent
QUESTIONS = EVALUATION / "questions.jsonl"
HELDOUT = EVALUATION / "heldout_questions.jsonl"
NEW_QUESTIONS = HERE / "questions.jsonl"
NEW_FOLLOW_UPS = HERE / "follow_ups.jsonl"
REPORT = HERE / "overlap_report.json"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "for",
    "from",
    "game",
    "games",
    "had",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "last",
    "of",
    "on",
    "or",
    "over",
    "season",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

OPPONENT_ALIASES = {
    "ATL": ("hawks", "atlanta"),
    "BKN": ("nets", "brooklyn"),
    "BOS": ("celtics", "boston", "celts", "c's"),
    "CHA": ("hornets", "charlotte"),
    "CHI": ("bulls", "chicago"),
    "CLE": ("cavaliers", "cavs", "cleveland"),
    "DAL": ("mavericks", "mavs", "dallas"),
    "DEN": ("nuggets", "denver"),
    "DET": ("pistons", "detroit"),
    "GSW": ("warriors", "golden state", "dubs", "gsw"),
    "HOU": ("rockets", "houston"),
    "IND": ("pacers", "indiana"),
    "LAC": ("clippers", "clips", "clipps"),
    "LAL": ("lakers", "lal"),
    "MEM": ("grizzlies", "memphis", "grizz"),
    "MIA": ("heat", "miami"),
    "MIL": ("bucks", "milwaukee"),
    "MIN": ("timberwolves", "wolves", "minnesota", "t-wolves"),
    "NOP": ("pelicans", "new orleans", "pels"),
    "NYK": ("knicks", "new york", "nyk", "bockers", "knickerbockers", "knics", "ny"),
    "OKC": ("thunder", "oklahoma city", "okc"),
    "ORL": ("magic", "orlando"),
    "PHI": ("76ers", "sixers", "philadelphia", "phi"),
    "PHX": ("suns", "phoenix"),
    "POR": ("trail blazers", "blazers", "portland"),
    "SAC": ("kings", "sacramento"),
    "SAS": ("spurs", "san antonio", "sas"),
    "TOR": ("raptors", "toronto", "raps"),
    "UTA": ("jazz", "utah"),
    "WAS": ("wizards", "washington", "wiz"),
}

PLAYER_ALIASES = {
    "Jalen Brunson": ("jalen brunson", "brunson", "jb"),
    "Karl-Anthony Towns": ("karl-anthony towns", "karl anthony towns", "towns", "kat", "big kat"),
    "Mikal Bridges": ("mikal bridges", "bridges", "mikal"),
    "Josh Hart": ("josh hart", "hart"),
    "OG Anunoby": ("og anunoby", "anunoby", "og"),
    "Mitchell Robinson": ("mitchell robinson", "mitch rob"),
    "Landry Shamet": ("landry shamet", "shamet", "sham"),
    "Miles McBride": ("miles mcbride", "mcbride", "deuce"),
    "Jordan Clarkson": ("jordan clarkson", "clarkson"),
    "Ariel Hukporti": ("ariel hukporti", "hukporti"),
    "Guerschon Yabusele": ("guerschon yabusele", "yabusele", "yabu"),
    "Jose Alvarado": ("jose alvarado", "alvarado"),
    "Tyler Kolek": ("tyler kolek", "kolek"),
    "Pacôme Dadiet": ("pacôme dadiet", "pacome dadiet", "dadiet"),
    "Mohamed Diawara": ("mohamed diawara", "mo diawara", "diawara"),
    "Jeremy Sochan": ("jeremy sochan", "sochan"),
    "Kevin McCullar Jr.": ("kevin mccullar jr.", "kevin mccullar", "mccullar"),
    "Trey Jemison III": ("trey jemison iii", "trey jemison", "jemison"),
    "Dillon Jones": ("dillon jones",),
    "Tosan Evbuomwan": ("tosan evbuomwan", "evbuomwan"),
}


def _patterns(values: tuple[str, ...]) -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(value)}\b", re.IGNORECASE) for value in values]


_OPPONENT_PATTERNS = {code: _patterns(values) for code, values in OPPONENT_ALIASES.items()}
_PLAYER_PATTERNS = {player: _patterns(values) for player, values in PLAYER_ALIASES.items()}
_MONTH_PATTERN = re.compile(r"\b(" + "|".join(MONTHS) + r")\b", re.IGNORECASE)
_MONTH_DAY_PATTERN = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\b", re.IGNORECASE)
_WINDOW_MARKER = re.compile(
    r"\b(between|from|through|until|since|before|after|over|in|during|for)\b", re.IGNORECASE
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _text(row: dict) -> str:
    parts = [str(row.get("question", ""))]
    for item in row.get("required_facts", []) or []:
        parts.append(str(item))
    for item in row.get("required_entities", []) or []:
        parts.append(str(item))
    parts.append(json.dumps(row.get("filters", {}), ensure_ascii=False))
    for turn in row.get("context", []) or []:
        parts.append(str(turn.get("content", "")))
    return " ".join(parts)


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.casefold())
        if word not in STOPWORDS and len(word) > 1
    }


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _entities(rows: list[dict]) -> tuple[set[str], set[str], set[str], set[int]]:
    players: set[str] = set()
    opponents: set[str] = set()
    months: set[str] = set()
    game_ids: set[int] = set()
    for row in rows:
        text = _text(row)
        for player, patterns in _PLAYER_PATTERNS.items():
            if any(pattern.search(text) for pattern in patterns):
                players.add(player)
        for code, patterns in _OPPONENT_PATTERNS.items():
            if code != "NYK" and any(pattern.search(text) for pattern in patterns):
                opponents.add(code)
        for match in _MONTH_PATTERN.finditer(text):
            months.add(match.group(1).casefold())
        filters = row.get("filters") or {}
        game_id = filters.get("game_id")
        if isinstance(game_id, int):
            game_ids.add(game_id)
    return players, opponents, months, game_ids


def _month_scoped(rows: list[dict]) -> set[str]:
    months: set[str] = set()
    for row in rows:
        filters = row.get("filters") or {}
        value = filters.get("month")
        if isinstance(value, str):
            months.add(value)
        values = filters.get("months")
        if isinstance(values, list):
            months.update(str(item) for item in values)
    return months


def _inferred_games(rows: list[dict], date_to_games: dict[tuple[int, int], list[int]]) -> set[int]:
    found: set[int] = set()
    for row in rows:
        filters = row.get("filters") or {}
        if isinstance(filters.get("game_id"), int):
            found.add(filters["game_id"])
            continue
        question = str(row.get("question", ""))
        if _WINDOW_MARKER.search(question):
            continue
        for match in _MONTH_DAY_PATTERN.finditer(question):
            month = MONTHS[match.group(1).casefold()]
            day = int(match.group(2))
            found.update(date_to_games.get((month, day), []))
    return found


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _date_map() -> dict[tuple[int, int], list[int]]:
    import asyncpg

    connection = await asyncpg.connect(dsn())
    try:
        archive = await load_archive(connection)
    finally:
        await connection.close()
    result: dict[tuple[int, int], list[int]] = {}
    for game in archive.games:
        result.setdefault((game.game_date.month, game.game_date.day), []).append(game.id)
    return result


def main() -> None:
    import asyncio

    existing = _read_jsonl(QUESTIONS)
    heldout = _read_jsonl(HELDOUT)
    new_main = _read_jsonl(NEW_QUESTIONS)
    new_follow = _read_jsonl(NEW_FOLLOW_UPS)
    if not new_main or not new_follow:
        raise SystemExit("generate the v2 set before running the overlap report")

    new_rows = new_main + new_follow
    new_texts = [(str(row["id"]), str(row["question"])) for row in new_rows]
    for row in new_follow:
        for turn in row.get("context", []) or []:
            if turn.get("role") == "user":
                new_texts.append((f"{row['id']}-turn1", str(turn["content"])))
    existing_texts = [(f"questions:{row['id']}", str(row["question"])) for row in existing] + [
        (f"heldout:{row['id']}", str(row["question"])) for row in heldout
    ]

    new_normal = {identifier: _normal(text) for identifier, text in new_texts}
    existing_normal = {identifier: _normal(text) for identifier, text in existing_texts}
    exact_matches = sorted(
        [
            {"new": new_id, "existing": existing_id}
            for new_id, text in new_normal.items()
            for existing_id, other in existing_normal.items()
            if text and text == other
        ],
        key=lambda item: (item["new"], item["existing"]),
    )

    pairs: list[tuple[float, str, str]] = []
    for new_id, text in new_texts:
        new_tokens = _tokens(text)
        for existing_id, other in existing_texts:
            similarity = _jaccard(new_tokens, _tokens(other))
            if similarity:
                pairs.append((round(similarity, 4), new_id, existing_id))
    pairs.sort(reverse=True)

    date_to_games = asyncio.run(_date_map())
    new_players, new_opponents, new_months_in_text, new_filter_games = _entities(new_rows)
    existing_players, existing_opponents, existing_months_in_text, existing_filter_games = (
        _entities(existing + heldout)
    )
    new_games = _inferred_games(new_rows, date_to_games)
    existing_games = _inferred_games(existing + heldout, date_to_games)
    new_months = _month_scoped(new_rows)
    existing_months = _month_scoped(existing + heldout)

    unresolved = [
        str(row["id"])
        for row in existing + heldout
        if row.get("category") in {"single_game_narrative", "turning_points", "follow_ups"}
        and (row.get("filters") or {}).get("game_id") is None
        and any(
            pattern.search(str(row.get("question", "")))
            for patterns in _OPPONENT_PATTERNS.values()
            for pattern in patterns
        )
        and not _MONTH_DAY_PATTERN.search(str(row.get("question", "")))
    ]

    report = {
        "new_set": {
            "main_questions": len(new_main),
            "follow_up_sessions": len(new_follow),
            "follow_up_turns": len(new_follow) * 2,
        },
        "checked_files": {
            "apps/api/app/evaluation/questions.jsonl": _sha(QUESTIONS),
            "apps/api/app/evaluation/heldout_questions.jsonl": _sha(HELDOUT),
            "apps/api/app/evaluation/heldout_v2/questions.jsonl": _sha(NEW_QUESTIONS),
            "apps/api/app/evaluation/heldout_v2/follow_ups.jsonl": _sha(NEW_FOLLOW_UPS),
        },
        "question_text": {
            "normalized_exact_matches": exact_matches,
            "max_token_jaccard": pairs[0][0] if pairs else 0.0,
            "pairs_at_or_above_0_8": sum(1 for score, _, _ in pairs if score >= 0.8),
            "pairs_at_or_above_0_6": sum(1 for score, _, _ in pairs if score >= 0.6),
            "top_pairs": [
                {"new_id": new_id, "existing_id": existing_id, "similarity": score}
                for score, new_id, existing_id in pairs[:10]
            ],
        },
        "entity_overlap": {
            "game_ids": {
                "new": sorted(new_games),
                "existing": sorted(existing_games),
                "overlap": sorted(new_games & existing_games),
            },
            "players": {
                "new": sorted(new_players),
                "existing": sorted(existing_players),
                "overlap": sorted(new_players & existing_players),
            },
            "opponents": {
                "new": sorted(new_opponents),
                "existing": sorted(existing_opponents),
                "overlap": sorted(new_opponents & existing_opponents),
            },
            "months_in_text": {
                "new": sorted(new_months_in_text),
                "existing": sorted(existing_months_in_text),
                "overlap": sorted(new_months_in_text & existing_months_in_text),
            },
            "month_scoped_questions": {
                "new": sorted(new_months),
                "existing": sorted(existing_months),
                "overlap": sorted(new_months & existing_months),
            },
        },
        "unresolved_existing_game_questions": sorted(set(unresolved)),
        "notes": [
            "Entity extraction reads question text, filters, required facts/entities and context.",
            "Game ids come from filters; for the public set a month-day is mapped to a game only "
            "when the question does not contain a window marker. Opponent-only narratives cannot "
            "be mapped to a single game id and are listed as unresolved.",
            "No held-out question text is written to this report.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "exact_matches": len(exact_matches),
                "max_jaccard": report["question_text"]["max_token_jaccard"],
                "at_or_above_0_8": report["question_text"]["pairs_at_or_above_0_8"],
                "game_overlap": report["entity_overlap"]["game_ids"]["overlap"],
                "player_overlap": report["entity_overlap"]["players"]["overlap"],
                "opponent_overlap": report["entity_overlap"]["opponents"]["overlap"],
                "month_scoped_overlap": report["entity_overlap"]["month_scoped_questions"][
                    "overlap"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
