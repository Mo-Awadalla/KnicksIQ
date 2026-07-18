"""Build the 120-question labelling queue.

The questions are committed as JSONL, while evidence IDs and canonical facts are
filled by a reviewer against a pinned data release. Web facts are candidates,
never automatic gold labels.
"""

from __future__ import annotations

import json
from pathlib import Path

CATEGORIES: dict[str, tuple[str | None, list[str]]] = {
    "exact_statistics": (
        "table_rag",
        [
            "What was the Knicks record this season?",
            "How many total points did the Knicks score?",
            "What was the Knicks average score per game?",
            "What was the Knicks average margin?",
            "How many home games did the Knicks win?",
            "How many road games did the Knicks win?",
            "How many games did the Knicks lose?",
            "What was the Knicks biggest win by margin?",
            "What was the Knicks worst loss by margin?",
            "What was the Knicks highest-scoring game?",
            "What was the Knicks lowest-scoring game?",
            "How many games did the Knicks score at least 120?",
            "How many games did the Knicks hold opponents under 100?",
            "What was Jalen Brunson's scoring average?",
            "How many total points did Jalen Brunson score?",
            "What was Karl-Anthony Towns' rebounding average?",
            "How many double-doubles did Towns have?",
            "Who led the Knicks in assists?",
            "Who led the Knicks in rebounds?",
            "Who led the Knicks in steals?",
            "What was Mikal Bridges' three-point percentage?",
            "How many games did Josh Hart start?",
            "What was OG Anunoby's scoring average?",
            "What was the Knicks record against Boston?",
            "How many points per game did the Knicks allow?",
        ],
    ),
    "date_range_last_n": (
        "table_rag",
        [
            "What was the Knicks record in their last 5 games?",
            "How many points did the Knicks average in their last 10 games?",
            "What was Brunson's scoring average over his last 5 games?",
            "How did the Knicks perform from January 1 through January 31?",
            "What was their record after the All-Star break?",
            "How many road games did they win in December?",
            "What was their average margin over the last 8 games?",
            "Who led the team in scoring over the last 3 games?",
            "How many games did they play between March 1 and March 15?",
            "What was their record in the first 10 games?",
            "How many points did Towns average in his last 7 games?",
            "What was the defense like over the last 5 games by points allowed?",
            "What was their record over the final 15 regular-season games?",
            "How many back-to-backs did they win in February?",
            "Compare their January record with their February record.",
        ],
    ),
    "comparisons": (
        "table_rag",
        [
            "Compare the Knicks' offense at home and on the road.",
            "Compare Brunson and Towns as scorers this season.",
            "Did the Knicks play better against Boston or Toronto?",
            "Compare their first 10 games with their last 10 games.",
            "Compare wins and losses by average turnover count.",
            "Was the bench more productive in home or away games?",
            "Compare the two Knicks games against Boston.",
            "Who had the better rebounding season, Towns or Hart?",
            "Compare the Knicks' third-quarter and fourth-quarter scoring.",
            "Did the Knicks shoot better in wins or losses?",
            "Compare Bridges' scoring before and after the All-Star break.",
            "Which was stronger: the Knicks offense or defense?",
            "Compare close games with blowouts.",
            "Did the Knicks fare better against Eastern or Western teams?",
            "Compare Brunson's last 5 games with his season average.",
        ],
    ),
    "single_game_narrative": (
        "retrieval_rag",
        [
            "How did the Knicks lose the lead against Boston?",
            "What decided the Knicks game against Toronto?",
            "Walk me through the fourth quarter against Atlanta.",
            "Why did the Knicks win the Chicago game?",
            "What changed after halftime against Charlotte?",
            "Tell the story of the closest Knicks game.",
            "How did Brunson influence the Boston game?",
            "What were the decisive possessions against Toronto?",
            "How did the Knicks close the Atlanta game?",
            "Why did the Knicks offense stall against Chicago?",
            "What did Towns do in the biggest win?",
            "Which plays swung the Charlotte game?",
            "How did the bench affect the Toronto game?",
            "What happened in the final two minutes against Boston?",
            "Explain the Knicks' best defensive game.",
            "How did turnovers shape the Atlanta game?",
            "What happened immediately after the Knicks took the lead against Chicago?",
            "Describe the Knicks' worst third quarter.",
            "How did the Knicks answer Toronto's late run?",
            "What was the key sequence in the Boston loss?",
        ],
    ),
    "turning_points": (
        "retrieval_rag",
        [
            "What was the Knicks' biggest scoring run against Boston?",
            "Where did the Toronto game turn?",
            "When did the Knicks collapse against Atlanta?",
            "What run broke open the Chicago game?",
            "How did the Knicks erase their largest deficit?",
            "Which drought cost the Knicks the Boston game?",
            "What was the most damaging opponent run this season?",
            "When did the Knicks lose control against Charlotte?",
            "What sequence started the comeback against Toronto?",
            "Which late-game possessions were the turning point against Atlanta?",
        ],
    ),
    "follow_ups": (
        "retrieval_rag",
        [
            "What happened next?",
            "Why was that stretch decisive?",
            "Who was on the floor then?",
            "How long did that run last?",
            "Did they recover after that?",
            "What did Brunson do during it?",
            "Show me the receipts for that.",
            "Was that their worst stretch?",
            "Compare that with the other Boston game.",
            "Tell me more about the final possession.",
        ],
    ),
    "aliases_typos": (
        "retrieval_rag",
        [
            "How did NYK do vs BOS?",
            "What happened agianst the Celts?",
            "How did JB play in that game?",
            "Tell me about KAT vs the Raps.",
            "What was the Knics biggest run?",
            "How did they do v ATL?",
            "What happened in the 4Q against CHI?",
            "Did Mikal play well aginst Toronto?",
            "How did OG look vs the C's?",
            "What was NY's worst collpase?",
        ],
    ),
    "unsupported": (
        None,
        [
            "What is the live score tonight?",
            "Will the Knicks win their next game?",
            "Who is injured today?",
            "What trade should the Knicks make tomorrow?",
            "Show possessions from 2099-01-01.",
            "What are the current Eastern Conference standings?",
            "Did the Knicks win yesterday?",
            "How will Brunson play next season?",
            "What happened in the Lakers game?",
            "Which Boston game do you mean?",
            "Was that a good game?",
            "What was the score?",
            "Who was better?",
            "Explain their defense.",
            "What is the best betting line for tonight?",
        ],
    ),
}

FOLLOW_UP_CONTEXT = [
    {"role": "user", "content": "How did the Knicks lose the lead against Boston?"},
    {
        "role": "assistant",
        "content": "Boston took control during a decisive second-half scoring run.",
    },
]


def build() -> list[dict]:
    cases: list[dict] = []
    for category, (route, questions) in CATEGORIES.items():
        for index, question in enumerate(questions, start=1):
            case = {
                "id": f"{category}-{index:03d}",
                "category": category,
                "question": question,
                "expected_route": route,
                "relevant_evidence_ids": [],
                "required_facts": [],
                "answerable": category != "unsupported",
                "filters": {},
                "label_status": "needs_archive_review",
            }
            if category == "follow_ups":
                case["context"] = FOLLOW_UP_CONTEXT
                case["filters"] = {"opponent": "BOS"}
            cases.append(case)
    return cases


def main() -> None:
    target = Path(__file__).with_name("questions.jsonl")
    cases = build()
    if len(cases) != 120:
        raise RuntimeError(f"expected 120 cases, got {len(cases)}")
    target.write_text(
        "".join(json.dumps(case, separators=(",", ":")) + "\n" for case in cases),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
