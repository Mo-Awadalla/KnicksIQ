"""ASGI entrypoint for a bounded service-profile evaluation candidate.

This module binds the approved run before the application is imported, so the
process can only answer readiness after its durable claim exists and every
provider request it makes is admitted against that run's ledger. A missing,
malformed or mismatched configuration raises at import, which stops uvicorn
before the socket serves anything.

It then wraps the application with the evaluation-only proof surface in
:mod:`app.evaluation.proof_surface`: the candidate signs one statement per
analyst response, and answers a side-effect-free preflight challenge, using the
run's private key from ``EVAL_RUN_PROOF_KEY``. A candidate that does not hold
the key bound in its configuration refuses to start.

Ordinary production starts ``app.main:app``, which loads none of this.
"""

from __future__ import annotations

import os

from app.evaluation.proof_surface import CandidateProofMiddleware, signer_for
from app.evaluation.provider_guard import bind_run_guard

_guard = bind_run_guard()
_signer = signer_for(_guard.binding, os.environ)

from app.main import app as _application  # noqa: E402  (binding above must precede readiness)

app = CandidateProofMiddleware(_application, _signer)

__all__ = ["app"]
