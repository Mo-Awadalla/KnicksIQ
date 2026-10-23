"""Provider wire format: claim packing, response encoding and scoped schemas."""

from __future__ import annotations

import json
from copy import deepcopy
from os.path import commonprefix
from typing import Any

from app.services.evidence_contracts import Action, AnswerReview, ProposedAnswer
from pydantic import BaseModel


def encoded(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def token_upper_bound(text: str) -> int:
    # UTF-8 bytes are a conservative upper bound for byte-level provider tokenizers.
    # This intentionally underfills the budget rather than truncating authoritative records.
    return len(text.encode("utf-8"))


def _pack_value_tables(value: Any) -> tuple[Any, dict[str, Any]]:
    """Factor repeated field names in complete ordered native object arrays."""
    tables: dict[str, Any] = {}

    def visit(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {
                key: visit(item, path + "/" + key.replace("~", "~0").replace("/", "~1"))
                for key, item in node.items()
            }
        if not isinstance(node, list):
            return node
        rows = [visit(item, path + "/" + str(index)) for index, item in enumerate(node)]
        if len(rows) < 2 or not all(isinstance(row, dict) for row in rows):
            return rows
        keys = list(rows[0])
        if not all(set(row) == set(keys) for row in rows):
            return rows
        context = {
            key: rows[0][key]
            for key in keys
            if all(
                json.dumps(row[key], sort_keys=True) == json.dumps(rows[0][key], sort_keys=True)
                for row in rows[1:]
            )
        }
        columns = [key for key in keys if key not in context]
        packed = [[row[key] for key in columns] for row in rows]
        table = [columns, context]
        if len(encoded(packed)) + len(encoded({path: table})) >= len(encoded(rows)):
            return rows
        tables[path] = table
        return packed

    return visit(value, ""), tables


def _restore_value_tables(value: Any, tables: dict[str, Any]) -> Any:
    def visit(node: Any, path: str) -> Any:
        if path in tables:
            table = tables[path]
            node = [{**table[1], **dict(zip(table[0], row, strict=True))} for row in node]
        if isinstance(node, dict):
            return {
                key: visit(item, path + "/" + key.replace("~", "~0").replace("/", "~1"))
                for key, item in node.items()
            }
        if isinstance(node, list):
            return [visit(item, path + "/" + str(index)) for index, item in enumerate(node)]
        return node

    return visit(value, "")


def _evidence_references(payload: dict[str, Any], refs: list[Any]) -> list[str]:
    ids = [entry["evidence_id"] for entry in payload.get("evidence", [])]
    restored = []
    for ref in refs:
        if type(ref) is int and 0 <= ref < len(ids):
            restored.append(ids[ref])
        elif isinstance(ref, str):
            restored.append(ref)
        else:
            raise ValueError("Packed evidence reference is outside its sealed domain")
    return restored


def payload_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Restore the complete records from the model input's shared claim context."""
    context = payload["claim_context"]
    restored = []
    for entry in payload["claims"]:
        record = {**context, **entry}
        if "eligibility_context" in payload:
            record["eligibility"] = {**payload["eligibility_context"], **record["eligibility"]}
        if isinstance(record.get("statement"), list):
            shared = payload["statement_context"]
            record["statement"] = shared["prefix"] + record["statement"][0] + shared["suffix"]
        if record.pop("statement_from_review", False):
            record["statement"] = "".join(payload["review_spans"])
        if "value_tables" in record:
            record["value"] = _restore_value_tables(record["value"], record.pop("value_tables"))
        record["supporting_evidence_ids"] = _evidence_references(
            payload, record["supporting_evidence_ids"]
        )
        prefix = record.pop("supporting_evidence_id_prefix", None)
        if prefix is not None:
            record["supporting_evidence_ids"] = [
                prefix + suffix for suffix in record["supporting_evidence_ids"]
            ]
        restored.append(record)
    return restored


def payload_claim_uses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Restore declared hint/choice rows, including their sealed numeric rounding."""
    claims = payload_claims(payload)
    return [
        {
            "claim_id": claims[index]["claim_id"],
            "displayed_value": (
                round(claims[index]["value"], precision)
                if precision is not None
                else claims[index]["value"]
            ),
            "decimal_places": precision,
        }
        for index, precision in payload.get("claim_uses", [])
    ]


def _claim_choice_rows(payload: dict[str, Any]) -> list[list[int | None]]:
    return [
        [index, precision]
        for index, claim in enumerate(payload_claims(payload))
        for precision in ([None, 0, 1, 2, 3] if type(claim["value"]) in (int, float) else [None])
    ]


def _finite_claim_uses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload_claim_uses({**payload, "claim_uses": _claim_choice_rows(payload)})


def _claim_choice_domains(payload: dict[str, Any]) -> tuple[list[list[int]], list[int]]:
    rows = _claim_choice_rows(payload)
    required = [
        [ordinal for ordinal, (claim_index, _) in enumerate(rows) if claim_index in domain]
        for domain in payload["required_claim_indexes"]
    ]
    related = [
        ordinal
        for ordinal, (claim_index, _) in enumerate(rows)
        if claim_index in payload.get("related_claim_indexes", [])
    ]
    return required, related


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Model response contains a duplicate JSON key")
        result[key] = value
    return result


def parse_model_response(raw: str) -> dict[str, Any]:
    """Reject duplicate keys before they can overwrite any sealed selection."""
    response = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(response, dict):
        raise ValueError("Model response must be a JSON object")
    return response


def payload_proposed_answer(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Restore declared uses without changing their IDs, types, precision or review text."""
    declared = payload.get("proposed_answer")
    if declared is None:
        return None
    claims = payload_claims(payload)
    answer = {
        key: value
        for key, value in declared.items()
        if key not in ("claim_uses", "value_overrides", "use_value_overrides")
    }
    answer["claims"] = [
        {
            "claim_id": claims[index]["claim_id"],
            "displayed_value": declared.get("use_value_overrides", {}).get(
                str(use_ordinal),
                declared.get("value_overrides", {}).get(str(index), claims[index]["value"]),
            ),
            "decimal_places": precision,
        }
        for use_ordinal, (index, precision) in enumerate(declared["claim_uses"])
    ]
    answer.setdefault("evidence_ids", [])
    answer["evidence_ids"] = _evidence_references(payload, answer["evidence_ids"])
    answer.setdefault("fact_ids", [])
    if "review_spans" in payload:
        answer["text"] = "".join(payload["review_spans"])
        answer["follow_up_questions"] = payload["follow_up_questions"]
    return answer


def _same_schema_value(left: Any, right: Any) -> bool:
    """JSON Schema numbers compare mathematically; booleans never equal numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_schema_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_schema_value(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _review_text_indexes(texts: list[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, text in enumerate(texts):
        indexes.setdefault(text, index)
    return indexes


def _model_response_values(
    payload: dict[str, Any], response: dict[str, Any], *, decode: bool
) -> dict[str, Any]:
    if payload.get("schema", {}).get("title") == "AnswerReview":
        result = deepcopy(response)
        for field, source, reference in (
            ("assertions", "review_spans", "span_index"),
            ("follow_up_reviews", "follow_up_questions", "follow_up_index"),
        ):
            texts = payload[source]
            indexes = _review_text_indexes(texts)
            for entry in result.get(field, []):
                if decode:
                    if "text" in entry:
                        raise ValueError("Review wire text must use its sealed index")
                    index = entry.pop(reference)
                    if type(index) is not int or index not in indexes.values():
                        raise ValueError("Review response changes a sealed text reference")
                    entry["text"] = texts[index]
                else:
                    if entry["text"] not in indexes:
                        raise ValueError("Review response changes a sealed text")
                    entry[reference] = indexes[entry.pop("text")]
                if payload.get("review_support_indexes"):
                    for support, rows, identity in (
                        ("supporting_claim_ids", "claims", "claim_id"),
                        ("supporting_evidence_ids", "evidence", "evidence_id"),
                    ):
                        if support not in entry:
                            continue
                        ids = [row[identity] for row in payload[rows]]
                        refs = entry[support]
                        if decode:
                            if not isinstance(refs, list) or any(
                                type(index) is not int or not 0 <= index < len(ids)
                                for index in refs
                            ):
                                raise ValueError(
                                    "Review response changes a sealed support reference"
                                )
                            entry[support] = [ids[index] for index in refs]
                        elif isinstance(refs, list):
                            # Invalid native fixtures remain invalid wire references.
                            if any(not isinstance(ref, str) for ref in refs):
                                raise ValueError("Native review support references must be IDs")
                            entry[support] = [ids.index(ref) if ref in ids else ref for ref in refs]
        return result
    if payload.get("required_claim_indexes"):
        result = deepcopy(response)
        answer = result.get("answer") if "action" in result else result
        if not isinstance(answer, dict):
            return result
        choices = _finite_claim_uses(payload)
        required, related = _claim_choice_domains(payload)
        if decode:
            selected = answer.get("claims")
            keys = {str(ordinal) for ordinal in range(len(required))}
            if not isinstance(selected, dict) or selected.keys() != keys:
                raise ValueError(
                    "Model response must select every required claim slot exactly once"
                )
            ordinals = []
            for ordinal, domain in enumerate(required):
                choice = selected[str(ordinal)]
                if type(choice) is not int or not 0 <= choice < len(domain):
                    raise ValueError("Model response changes a required sealed claim choice")
                ordinals.append(domain[choice])
            if related:
                tail = answer.pop("related_claims", None)
                if not isinstance(tail, list):
                    raise ValueError("Model response must declare its related claim choices")
                if any(
                    type(choice) is not int or not 0 <= choice < len(related) for choice in tail
                ):
                    raise ValueError("Model response changes a related sealed claim choice")
                ordinals.extend(related[choice] for choice in tail)
            elif "related_claims" in answer:
                raise ValueError("Model response adds forbidden related claim choices")
            selected_uses = [choices[ordinal] for ordinal in ordinals]
            if len({use["claim_id"] for use in selected_uses}) != len(selected_uses):
                raise ValueError("Model response selects a sealed claim more than once")
            answer["claims"] = selected_uses
            return result
        # Scripted invalid native fixtures stay invalid wire. Encoding must not
        # complete a missing slot, drop a duplicate, or repair a wrong value.
        uses = answer.get("claims")
        if not isinstance(uses, list) or "related_claims" in answer:
            return result
        selected_ordinals = []
        for use in uses:
            if not isinstance(use, dict) or set(use) - {
                "claim_id",
                "displayed_value",
                "decimal_places",
            }:
                return result
            precision = use.get("decimal_places")
            if precision is not None and type(precision) is not int:
                return result
            matches = [
                ordinal
                for ordinal, choice in enumerate(choices)
                if use.get("claim_id") == choice["claim_id"]
                and precision == choice["decimal_places"]
                and _same_schema_value(use.get("displayed_value"), choice["displayed_value"])
            ]
            if len(matches) != 1:
                return result
            selected_ordinals.append(matches[0])
        if len({use["claim_id"] for use in uses}) != len(uses):
            return result
        slots = {}
        for ordinal, domain in enumerate(required):
            matches = [choice for choice in selected_ordinals if choice in domain]
            if len(matches) != 1:
                return result
            slots[str(ordinal)] = matches[0]
        tail = [choice for choice in selected_ordinals if choice not in slots.values()]
        if len(uses) > 30 or any(choice not in related for choice in tail):
            return result
        # The model counts each slot's choices from 0, so a choice keeps one meaning in every
        # slot and no slot depends on how many rows precede it in the shared claim_uses table.
        answer["claims"] = {
            slot: required[int(slot)].index(ordinal) for slot, ordinal in slots.items()
        }
        if related:
            answer["related_claims"] = [related.index(choice) for choice in tail]
        return result
    if not any("value_tables" in claim for claim in payload["claims"]):
        return response
    result = deepcopy(response)
    answer = result.get("answer") if "action" in result else result
    if not isinstance(answer, dict) or "claims" not in answer:
        return result
    native = {claim["claim_id"]: claim for claim in payload_claims(payload)}
    wire = {claim["claim_id"]: claim for claim in payload["claims"]}
    for use in answer["claims"]:
        claim_id = use["claim_id"]
        if claim_id not in native:
            raise ValueError("Model response references an unknown sealed claim")
        record = wire[claim_id]
        if "value_tables" not in record:
            continue
        expected = record["value"] if decode else native[claim_id]["value"]
        if not _same_schema_value(use["displayed_value"], expected):
            raise ValueError("Model response changes a complete sealed table value")
        use["displayed_value"] = (
            _restore_value_tables(record["value"], record["value_tables"])
            if decode
            else record["value"]
        )
    return result


def encode_model_response(payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Encode native scripted answers in the same exact model-wire value language."""
    return _model_response_values(payload, response, decode=False)


def decode_model_response(payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Restore only actually selected sealed choices/tables before native validation."""
    return _model_response_values(payload, response, decode=True)


def _wire_payload(payload: dict[str, Any], *, complete: bool = False) -> dict[str, Any]:
    indexes = {claim["claim_id"]: index for index, claim in enumerate(payload["claims"])}
    wire = dict(payload)
    if payload.get("required_claim_indexes"):
        wire["claim_uses"] = _claim_choice_rows(payload)
        wire["claim_context_format"] += (
            " claim_uses=[claim_index,precision]; each required slot selects an index among"
            " the claim_uses rows whose claim index is in that slot; related_claims mirrors"
            " related_claim_indexes."
        )
    elif "claim_uses" in payload:
        wire["claim_uses"] = [
            [indexes[use["claim_id"]], use.get("decimal_places")] for use in payload["claim_uses"]
        ]
        wire["claim_context_format"] += (
            " claim_uses=[claim_index,precision] -> claim_id,claim.value,decimal_places."
        )
    declared = payload.get("proposed_answer")
    if declared is None:
        return wire
    if not all(use["claim_id"] in indexes for use in declared["claims"]):
        if complete:
            raise ValueError("Complete declared claims exceed model input budget")
        # Budget construction has not yet admitted the complete referenced group.
        return wire
    claims = payload_claims(payload)
    wire["proposed_answer"] = {
        **{key: value for key, value in declared.items() if key != "claims"},
        "claim_uses": [
            [indexes[use["claim_id"]], use.get("decimal_places")] for use in declared["claims"]
        ],
    }
    evidence_indexes = {
        entry["evidence_id"]: index for index, entry in enumerate(payload["evidence"])
    }
    if (
        payload.get("schema", {}).get("title") == "AnswerReview"
        and "evidence_ids" in wire["proposed_answer"]
    ):
        wire["proposed_answer"]["evidence_ids"] = [
            evidence_indexes.get(ref, ref) for ref in declared["evidence_ids"]
        ]
    overrides = {
        str(indexes[use["claim_id"]]): use["displayed_value"]
        for use in declared["claims"]
        if json.dumps(use["displayed_value"], sort_keys=True, ensure_ascii=False)
        != json.dumps(
            claims[indexes[use["claim_id"]]]["value"],
            sort_keys=True,
            ensure_ascii=False,
        )
    }
    if overrides:
        wire["proposed_answer"]["value_overrides"] = overrides
    # A malformed historical proposal may declare one ID multiple times with
    # different values. Preserve each actual use, not just the last ID override.
    use_overrides = {
        str(ordinal): use["displayed_value"]
        for ordinal, use in enumerate(declared["claims"])
        if json.dumps(use["displayed_value"], sort_keys=True, ensure_ascii=False)
        != json.dumps(
            overrides.get(str(indexes[use["claim_id"]]), claims[indexes[use["claim_id"]]]["value"]),
            sort_keys=True,
            ensure_ascii=False,
        )
    }
    if use_overrides:
        wire["proposed_answer"]["use_value_overrides"] = use_overrides
        wire["claim_context_format"] += " use_value_overrides uses declared-use ordinals."
    return wire


def _pack_claims(payload: dict[str, Any], claims: list[dict[str, Any]]) -> None:
    """Factor repeated presentation fields without changing complete native records."""
    provenance_annotation = " supporting_evidence_ids=prefix+suffix (concatenate each)."
    payload["claim_context_format"] = payload["claim_context_format"].replace(
        provenance_annotation, ""
    )
    records = [dict(claim) for claim in claims]
    prefixes = []
    for record in records:
        refs = record["supporting_evidence_ids"]
        prefix = commonprefix(refs)
        suffixes = [ref[len(prefix) :] for ref in refs]
        if prefix and len(encoded(refs)) > (
            len(encoded(suffixes)) + len(encoded(prefix)) + 40 + len(provenance_annotation)
        ):
            record["supporting_evidence_ids"] = suffixes
            prefixes.append(prefix)
        else:
            prefixes.append(None)
    if any(prefixes):
        for record, prefix in zip(records, prefixes, strict=True):
            record["supporting_evidence_id_prefix"] = prefix
        payload["claim_context_format"] += provenance_annotation
    context = {}
    if records:
        for key in records[0]:
            if key in {"claim_id", "metric_id", "value", "statement"}:
                continue
            if not all(key in record for record in records):
                continue
            counts: dict[str, int] = {}
            for claim in records:
                value = encoded(claim[key])
                counts[value] = counts.get(value, 0) + 1
            shared = max(counts, key=lambda value: counts[value])
            if counts[shared] > 1:
                context[key] = json.loads(shared)
    payload["claim_context"] = context
    payload["claims"] = [
        {
            key: value
            for key, value in claim.items()
            if key not in context or encoded(value) != encoded(context[key])
        }
        for claim in records
    ]
    eligibility_annotation = " Eligibility inherits eligibility_context; row keys override."
    payload["claim_context_format"] = payload["claim_context_format"].replace(
        eligibility_annotation, ""
    )
    payload.pop("eligibility_context", None)
    if len(records) > 1:
        shared_eligibility = {
            key: value
            for key, value in records[0]["eligibility"].items()
            if all(
                key in record["eligibility"]
                and encoded(record["eligibility"][key]) == encoded(value)
                for record in records[1:]
            )
        }
        if shared_eligibility:
            candidate_context = {
                key: value for key, value in context.items() if key != "eligibility"
            }
            candidate_entries = [
                {
                    **entry,
                    "eligibility": {
                        key: value
                        for key, value in record["eligibility"].items()
                        if key not in shared_eligibility
                    },
                }
                for entry, record in zip(payload["claims"], records, strict=True)
            ]
            candidate = {
                "claim_context": candidate_context,
                "claims": candidate_entries,
                "eligibility_context": shared_eligibility,
            }
            baseline = {"claim_context": context, "claims": payload["claims"]}
            if len(encoded(candidate)) + len(eligibility_annotation) < len(encoded(baseline)):
                payload.update(candidate)
                payload["claim_context_format"] += eligibility_annotation
    # Native statements stay byte-identical; only repeated presentation affixes move.
    annotation = " Array statement=prefix+only item+suffix."
    payload["claim_context_format"] = payload["claim_context_format"].replace(annotation, "")
    payload.pop("statement_context", None)
    groups: dict[str, list[int]] = {}
    for index, claim in enumerate(claims):
        groups.setdefault(encoded(claim["subject_id"]), []).append(index)
    baseline_size = token_upper_bound(encoded({"claims": payload["claims"]}))
    best_size = baseline_size
    best = None
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        statements = [claims[index]["statement"] for index in indexes]
        prefix = commonprefix(statements)
        suffix = commonprefix([text[len(prefix) :][::-1] for text in statements])[::-1]
        if not prefix and not suffix:
            continue
        entries = [dict(entry) for entry in payload["claims"]]
        for index in indexes:
            text = claims[index]["statement"]
            entries[index]["statement"] = [
                text[len(prefix) : len(text) - len(suffix) if suffix else len(text)]
            ]
        shared = {"prefix": prefix, "suffix": suffix}
        candidate_size = token_upper_bound(
            encoded({"claims": entries, "statement_context": shared})
        ) + token_upper_bound(annotation)
        if candidate_size < best_size:
            best_size = candidate_size
            best = entries, shared
    if best is not None:
        payload["claims"], payload["statement_context"] = best
        payload["claim_context_format"] += annotation
    table_annotation = (
        " value_tables[path]=[columns,context]: JSON-pointer array rows map to columns"
        " and inherit context; output displayed_value copies packed claim.value."
    )
    statement_annotation = " statement_from_review:true=>statement=concat(review_spans)."
    payload["claim_context_format"] = (
        payload["claim_context_format"]
        .replace(table_annotation, "")
        .replace(statement_annotation, "")
    )
    has_tables = False
    has_statement_reference = False
    for entry, native in zip(payload["claims"], claims, strict=True):
        packed, tables = _pack_value_tables(native["value"])
        if tables and (
            len(encoded(packed)) + len(encoded(tables)) + len(table_annotation) + 17
            < len(encoded(native["value"]))
        ):
            entry["value"] = packed
            entry["value_tables"] = tables
            has_tables = True
        if native["statement"] == "".join(payload.get("review_spans", [])):
            entry.pop("statement", None)
            entry["statement_from_review"] = True
            has_statement_reference = True
    if has_tables:
        payload["claim_context_format"] += table_annotation
    if has_statement_reference:
        payload["claim_context_format"] += statement_annotation


def payload_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Restore native receipts, including metadata identical to their JSON source text."""
    restored = []
    for entry in payload["evidence"]:
        record = {**payload["evidence_context"], **entry}
        if "text_claim" in record:
            record["text"] = payload_claims(payload)[record.pop("text_claim")]["statement"]
        if isinstance(record["text"], dict):
            record["text"] = json.dumps(record["text"], sort_keys=True)
        if record.pop("metadata_from_text"):
            record["metadata"] = json.loads(record["text"])
        if "source_ids_claim" in record:
            index, first = record.pop("source_ids_claim")
            games = payload_claims(payload)[index]["eligibility"]["comparison"]["game_ids"]
            record["metadata"] = {
                **record["metadata"],
                "source_evidence_ids": first
                + [str(game) for game in games if str(game) not in first],
            }
        prefix = record.pop("source_evidence_id_prefix", None)
        suffix = record.pop("source_evidence_id_suffix", None)
        if prefix is not None or suffix is not None:
            record["metadata"] = {
                **record["metadata"],
                "source_evidence_ids": [
                    (prefix or "") + middle + (suffix or "")
                    for middle in record["metadata"]["source_evidence_ids"]
                ],
            }
        restored.append(record)
    return restored


def _pack_evidence(payload: dict[str, Any], records: list[dict[str, Any]]) -> None:
    review = payload.get("schema", {}).get("title") == "AnswerReview"
    suffix_annotation = " source_evidence_id_suffix follows each source_evidence_ids fragment."
    source_annotation = (
        " source_ids_claim=[claim index,first]; source IDs=first+comparison.game_ids"
        " excluding first, then prefix."
    )
    text_annotation = " text_claim indexes claims[].statement."
    reference_annotation = (
        " Integer claim/proposed evidence IDs index evidence rows; strings are IDs."
    )
    native_claims = payload_claims(payload)
    entries = []
    uses_source_reference = False
    uses_text_reference = False
    for record in records:
        entry = {**record, "metadata_from_text": False}
        try:
            parsed = json.loads(record["text"])
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict) and json.dumps(parsed, sort_keys=True) == json.dumps(
            record["metadata"], sort_keys=True
        ):
            entry["metadata_from_text"] = True
            entry.pop("metadata")
        else:
            refs = record["metadata"].get("source_evidence_ids")
            if isinstance(refs, list) and refs and all(isinstance(ref, str) for ref in refs):
                prefix = commonprefix(refs)
                suffixes = [ref[len(prefix) :] for ref in refs]
                if prefix and len(encoded(refs)) > len(encoded(suffixes)) + len(prefix) + 40:
                    entry["source_evidence_id_prefix"] = prefix
                    entry["metadata"] = {**record["metadata"], "source_evidence_ids": suffixes}
                fragments = entry["metadata"]["source_evidence_ids"]
                suffix = commonprefix([fragment[::-1] for fragment in fragments])[::-1]
                middles = [fragment[: -len(suffix)] for fragment in fragments] if suffix else []
                if suffix and len(encoded(fragments)) > (
                    len(encoded(middles))
                    + len(encoded({"source_evidence_id_suffix": suffix}))
                    + len(suffix_annotation)
                ):
                    entry["source_evidence_id_suffix"] = suffix
                    entry["metadata"] = {**entry["metadata"], "source_evidence_ids": middles}
        if isinstance(parsed, dict) and json.dumps(parsed, sort_keys=True) == record["text"]:
            entry["text"] = parsed
        if not entry["metadata_from_text"]:
            fragments = entry["metadata"].get("source_evidence_ids")
            if isinstance(fragments, list) and not entry.get("source_evidence_id_suffix"):
                for index, claim in enumerate(native_claims):
                    games = claim["eligibility"].get("comparison", {}).get("game_ids", [])
                    if not games or any(type(game) is not int for game in games):
                        continue
                    strings = [str(game) for game in games]
                    if len(set(strings)) != len(strings):
                        continue
                    for count in range(min(3, len(fragments)) + 1):
                        first = fragments[:count]
                        if first + [game for game in strings if game not in first] != fragments:
                            continue
                        candidate = {
                            **entry,
                            "metadata": {
                                key: value
                                for key, value in entry["metadata"].items()
                                if key != "source_evidence_ids"
                            },
                            "source_ids_claim": [index, first],
                        }
                        annotation_size = 0 if uses_source_reference else len(source_annotation)
                        if len(encoded(candidate)) + annotation_size < len(encoded(entry)):
                            entry = candidate
                            uses_source_reference = True
                        break
                    if "source_ids_claim" in entry:
                        break
        for index, claim in enumerate(native_claims if review else []):
            if record["text"] != claim["statement"]:
                continue
            candidate = {key: value for key, value in entry.items() if key != "text"}
            candidate["text_claim"] = index
            annotation_size = 0 if uses_text_reference else len(text_annotation)
            if len(encoded(candidate)) + annotation_size < len(encoded(entry)):
                entry = candidate
                uses_text_reference = True
            break
        entries.append(entry)
    context = {}
    if entries:
        for key in (
            "release_id",
            "game_id",
            "source_name",
            "source_url",
            "metadata_from_text",
            "metadata",
            "source_evidence_id_prefix",
            "source_evidence_id_suffix",
        ):
            counts: dict[str, int] = {}
            for entry in entries:
                if key in entry:
                    code = encoded(entry[key])
                    counts[code] = counts.get(code, 0) + 1
            if counts:
                code, count = max(counts.items(), key=lambda item: item[1])
                if count > 1:
                    context[key] = json.loads(code)
    payload["evidence_context"] = context
    payload["evidence"] = [
        {
            **{
                key: value
                for key, value in entry.items()
                if key not in context or encoded(value) != encoded(context[key])
            },
            **{key: None for key in context if key not in entry},
        }
        for entry in entries
    ]
    ids = {entry["evidence_id"]: index for index, entry in enumerate(entries)}
    packed_claims = []
    for record in (payload["claim_context"], *payload["claims"]):
        packed = dict(record)
        prefix = record.get(
            "supporting_evidence_id_prefix",
            payload["claim_context"].get("supporting_evidence_id_prefix"),
        )
        if review and "supporting_evidence_ids" in record and prefix is None:
            packed["supporting_evidence_ids"] = [
                ids.get(ref, ref) for ref in record["supporting_evidence_ids"]
            ]
        packed_claims.append(packed)
    payload["claim_context"] = packed_claims[0]
    payload["claims"] = packed_claims[1:]
    uses_id_reference = review and (
        any(
            type(ref) is int
            for record in packed_claims
            for ref in record.get("supporting_evidence_ids", [])
        )
        or any(ref in ids for ref in (payload.get("proposed_answer") or {}).get("evidence_ids", []))
    )
    annotations = (
        " metadata_from_text:true=>metadata=JSON(text).",
        " source_evidence_ids=source_evidence_id_prefix+suffixes.",
        suffix_annotation,
        " Object text=canonical JSON.",
        source_annotation,
        text_annotation,
        reference_annotation,
    )
    for annotation in annotations:
        payload["claim_context_format"] = payload["claim_context_format"].replace(annotation, "")
    used = (
        any(entry["metadata_from_text"] for entry in entries),
        any("source_evidence_id_prefix" in entry for entry in entries),
        any("source_evidence_id_suffix" in entry for entry in entries),
        any(isinstance(entry.get("text"), dict) for entry in entries),
        uses_source_reference,
        uses_text_reference,
        uses_id_reference,
    )
    for annotation, needed in zip(annotations, used, strict=True):
        if needed:
            payload["claim_context_format"] += annotation


def compact_schema(schema: type) -> dict[str, Any]:
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip(child)
                for key, child in value.items()
                if key not in {"title", "description", "default"}
            }
        if isinstance(value, list):
            return [strip(child) for child in value]
        return value

    result = strip(schema.model_json_schema())
    result["title"] = schema.__name__
    return result


def _complete_object_alternatives(schema: dict[str, Any]) -> None:
    """Emit complete object branches instead of partial property intersections."""
    common = {key: value for key, value in schema.items() if key not in {"anyOf", "$defs"}}
    branches = []
    for constraints in schema["anyOf"]:
        branch = deepcopy(common)
        branch.update(
            {
                key: deepcopy(value)
                for key, value in constraints.items()
                if key not in {"properties", "required"}
            }
        )
        for name, constraint in constraints.get("properties", {}).items():
            branch["properties"][name].update(deepcopy(constraint))
        branch["required"] = sorted(
            set(common.get("required", [])) | set(constraints.get("required", []))
        )
        branches.append(branch)
    schema["anyOf"] = branches
    for key in ("properties", "required", "additionalProperties"):
        schema.pop(key, None)


def scoped_response_schema(schema: type[BaseModel], payload: dict[str, Any]) -> dict[str, Any]:
    """Constrain provider output to references and complete values actually supplied."""
    result = compact_schema(schema)
    definitions = result.get("$defs", {})
    if schema is Action:
        from app.services.evidence_contracts import PLAYER_METRICS

        # Optional fields retain runtime defaults, but each action must be executable.
        result["anyOf"] = [
            {
                "properties": {
                    "action": {"enum": ["call_tools"]},
                    "tools": {"minItems": 1},
                    "answer": {"type": "null"},
                },
                "required": ["tools"],
            },
            {
                "properties": {
                    "action": {
                        "enum": [
                            action
                            for action in result["properties"]["action"]["enum"]
                            if action != "call_tools"
                        ]
                    },
                    "tools": {"maxItems": 0},
                    "answer": {"$ref": "#/$defs/ProposedAnswer"},
                },
                "required": ["answer"],
            },
        ]
        player_tools = ["get_player_stats", "find_player_games", "compare_windows"]
        tool_schema = definitions["ToolCall"]
        tool_schema["anyOf"] = [
            {
                "properties": {
                    "name": {"enum": player_tools},
                    "metric": {"enum": [*PLAYER_METRICS, None]},
                }
            },
            {
                "properties": {
                    "name": {
                        "enum": [
                            name
                            for name in tool_schema["properties"]["name"]["enum"]
                            if name not in player_tools
                        ]
                    }
                }
            },
        ]
    keyed = bool(payload.get("required_claim_indexes")) and schema is not AnswerReview
    uses = _finite_claim_uses(payload)
    if not keyed:
        uses = _model_response_values(payload, {"claims": uses}, decode=False)["claims"]
    if "ClaimUse" in definitions and uses and not keyed:
        alternatives = []
        for claim in payload_claims(payload):
            choices = [use for use in uses if use["claim_id"] == claim["claim_id"]]
            values = {}
            for use in choices:
                key = encoded(use["displayed_value"])
                values.setdefault(key, []).append(use["decimal_places"])
            branches = [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim_id", "displayed_value", "decimal_places"],
                    "properties": {
                        "claim_id": {"enum": [claim["claim_id"]]},
                        "displayed_value": {"enum": [json.loads(value)]},
                        "decimal_places": {"enum": places},
                    },
                }
                for value, places in values.items()
            ]
            # Equal rounded values share their ID and value without permitting
            # a precision/value pair absent from the original complete-object enum.
            enum = {"enum": choices}
            grouped = {"anyOf": branches}
            alternatives.append(grouped if len(encoded(grouped)) < len(encoded(enum)) else enum)
        definitions["ClaimUse"] = {"anyOf": alternatives}

    def restrict_array(properties: dict[str, Any], key: str, values: list[str]) -> None:
        if values:
            properties[key]["items"] = (
                {"type": "integer", "enum": list(range(len(values)))}
                if schema is AnswerReview and payload.get("review_support_indexes")
                else {"type": "string", "enum": values}
            )
        else:
            properties[key]["maxItems"] = 0

    answer_schema = result if schema is ProposedAnswer else definitions.get("ProposedAnswer")
    if answer_schema:
        properties = answer_schema["properties"]
        if keyed:
            required, related = _claim_choice_domains(payload)
            properties["claims"] = {
                "type": "object",
                "additionalProperties": False,
                "required": [str(ordinal) for ordinal in range(len(required))],
                "properties": {
                    str(ordinal): {"type": "integer", "enum": list(range(len(domain)))}
                    for ordinal, domain in enumerate(required)
                },
            }
            definitions.pop("ClaimUse", None)
            if related:
                properties["related_claims"] = {
                    "type": "array",
                    "items": {"type": "integer", "enum": list(range(len(related)))},
                    "maxItems": max(0, 30 - len(required)),
                }
        elif not uses:
            properties["claims"]["maxItems"] = 0
        answer_schema["required"] = list(properties)
        restrict_array(properties, "fact_ids", [c["fact_id"] for c in payload["candidates"]])
        restrict_array(properties, "evidence_ids", [e["evidence_id"] for e in payload["evidence"]])
    if schema is AnswerReview:
        properties = definitions["AssertionReview"]["properties"]
        properties.pop("text")
        definitions["AssertionReview"]["required"] = [
            "span_index" if key == "text" else key
            for key in definitions["AssertionReview"]["required"]
        ]
        properties["span_index"] = {
            "type": "integer",
            "enum": list(_review_text_indexes(payload["review_spans"]).values()),
        }
        restrict_array(
            properties, "supporting_claim_ids", [c["claim_id"] for c in payload["claims"]]
        )
        restrict_array(
            properties, "supporting_evidence_ids", [e["evidence_id"] for e in payload["evidence"]]
        )
        if payload["follow_up_questions"]:
            suggestions = definitions["FollowUpReview"]["properties"]
            suggestions.pop("text")
            definitions["FollowUpReview"]["required"] = [
                "follow_up_index" if key == "text" else key
                for key in definitions["FollowUpReview"]["required"]
            ]
            suggestions["follow_up_index"] = {
                "type": "integer",
                "enum": list(_review_text_indexes(payload["follow_up_questions"]).values()),
            }
            restrict_array(
                suggestions, "supporting_claim_ids", [c["claim_id"] for c in payload["claims"]]
            )
            restrict_array(
                suggestions,
                "supporting_evidence_ids",
                [e["evidence_id"] for e in payload["evidence"]],
            )
        else:
            result["properties"]["follow_up_reviews"] = {"type": "array", "maxItems": 0}
            definitions.pop("FollowUpReview")
    if schema is Action:
        _complete_object_alternatives(definitions["ToolCall"])
        _complete_object_alternatives(result)
        # Stronger branch constraints subsume these common nullable/item schemas.
        # Keep the complete alternatives small enough to retain requested claims.
        tool_branch, answer_branch = result["anyOf"]
        tool_branch["properties"]["answer"] = {"type": "null"}
        answer_branch["properties"]["answer"] = {"$ref": "#/$defs/ProposedAnswer"}
        answer_branch["properties"]["tools"] = {"type": "array", "maxItems": 0}
        player_metric = definitions["ToolCall"]["anyOf"][0]["properties"]["metric"]
        player_metric.pop("anyOf")

    # Definition labels are repeated formatting, not protocol fields or evidence IDs.
    references = {f"#/$defs/{name}": f"#/$defs/{index}" for index, name in enumerate(definitions)}
    if definitions:
        result["$defs"] = {
            str(index): definition for index, definition in enumerate(definitions.values())
        }
    else:
        result.pop("$defs", None)

    def simplify_closed_values(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference in references:
                value["$ref"] = references[reference]
            if value.get("maxItems") == 0:
                value.pop("items", None)
            choices = value.get("enum")
            if choices:
                kind = value.get("type")
                implied = (
                    {
                        "string": lambda item: isinstance(item, str),
                        "boolean": lambda item: type(item) is bool,
                        "null": lambda item: item is None,
                        "number": lambda item: type(item) in (int, float),
                        "integer": lambda item: (
                            type(item) is int or (type(item) is float and item.is_integer())
                        ),
                    }.get(kind)
                    if isinstance(kind, str)
                    else None
                )
                if (
                    not (keyed and kind == "integer")
                    and implied
                    and all(implied(item) for item in choices)
                ):
                    value.pop("type")
                if all(isinstance(item, str) for item in choices):
                    if "minLength" in value and all(
                        len(item) >= value["minLength"] for item in choices
                    ):
                        value.pop("minLength")
                    if "maxLength" in value and all(
                        len(item) <= value["maxLength"] for item in choices
                    ):
                        value.pop("maxLength")
            for key, child in value.items():
                # Enum/const contents are immutable literal values, not schemas.
                if key not in {"enum", "const"}:
                    simplify_closed_values(child)
        elif isinstance(value, list):
            for child in value:
                simplify_closed_values(child)

    simplify_closed_values(result)
    if schema is AnswerReview and payload["follow_up_questions"]:
        review_keys = [
            result["properties"][name]["items"]["$ref"].removeprefix("#/$defs/")
            for name in ("assertions", "follow_up_reviews")
        ]
        for name in ("supporting_claim_ids", "supporting_evidence_ids"):
            definitions = result["$defs"]
            assertion = definitions[review_keys[0]]["properties"]
            suggestion = definitions[review_keys[1]]["properties"]
            if encoded(assertion[name]) != encoded(suggestion[name]):
                continue
            candidate = deepcopy(result)
            shared_key = str(len(definitions))
            candidate["$defs"][shared_key] = deepcopy(assertion[name])
            for key in review_keys:
                candidate["$defs"][key]["properties"][name] = {"$ref": f"#/$defs/{shared_key}"}
            if len(encoded(candidate)) < len(encoded(result)):
                result = candidate
    return result
