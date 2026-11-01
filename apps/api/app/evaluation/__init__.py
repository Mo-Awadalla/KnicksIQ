"""Offline quality evaluation for the analyst pipeline.

Labels, observation parsing and scoring are typed and fail closed; a missing
expectation, trace, reviewer decision, evidence-registry receipt or mapping entry
blocks a metric instead of passing it. Every one of the 120 cases needs a review
bound to its exact response, and no approval is inferred from a boolean.
See ``docs/evaluation.md``.
"""
