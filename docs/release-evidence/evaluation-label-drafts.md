# Evaluation label drafts

[120 machine-readable drafts](evaluation-label-drafts.jsonl) bind canonical facts and NBA game
identities to the local baseline SHA-256. Regenerate with `python3 tools/release/draft_labels.py`.
They are review material, not passing evaluation evidence. No label is owner-approved.

Facts include scorelines, records, home/away splits, player totals and per-appearance rates,
quarter totals and team box totals. Source keys remain canonical NBA game/player IDs until
verified candidate-index payloads supply retrieval IDs. The original fixed question set is
unchanged. Promotion requires the owner to choose the exact required claims, accepted
paraphrases, entity allowlists, claim-level evidence IDs and any clarification expectations.

Review in the original category batches: exact statistics (25), date ranges (15), comparisons
(15), single-game narrative (20), turning points (10), follow-ups (10), aliases/typos (10),
and unsupported (15). Pin date boundaries and ambiguous references. A seasonal player rate
must specify appearances versus team games. Draft player windows follow the question's
selected team-game window; questions specifying a player's last appearances require review
against that player's appearance sequence before approval.

Several semantic questions identify an opponent but no unique game. Some original
"unsupported" questions refer to archived opponents or need clarification rather than
refusal. The run audit also prevents approving causal run descriptions. These disagreements
must be adjudicated before fixing the reviewed semantic set; do not silently relabel misses
or drop difficult cases to meet Recall@5.
