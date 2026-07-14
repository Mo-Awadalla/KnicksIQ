# Answer and retrieval evaluation

The launch evaluation set is a human-reviewed JSONL artifact kept with the private release inputs. Each case contains a paraphrased question, capability category, canonical answer facts, allowed entity names, required claim-level citations, and expected refusal status.

Release gates are: 100% canonical numeric/entity correctness; at least 95% overall paraphrase and citation pass rate; at least 95% Recall@5 for semantic questions; and 100% explicit refusal for unsupported tactical, live, injury, trade, future, or non-archive claims. Tests run once with Qdrant enabled and again with Qdrant, Redis, and OpenRouter disabled. The deterministic answer must remain correct in both runs.
