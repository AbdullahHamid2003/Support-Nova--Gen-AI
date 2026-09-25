"""End-to-end complaint processing (the SupportNova flow):

submission -> preprocessing (normalise, screen, redact, perceive, history, duplicates) -> retrieval ->
GenAI analysis (structured JSON, controlled retries) -> Python ground-truth validation (Phase A) ->
validated decision -> GenAI customer communication -> Python response validation (Phase B) ->
verification score & decision -> resolution / response / escalation / follow-up / SLA / review ->
audit trail. AI proposes. Python validates. Ground truth decides.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.complaint_processing.fact_builder import build_perception
from supportnova.core.config import get_settings
from supportnova.core.logging import get_logger
from supportnova.core.timeutil import utcnow
from supportnova.database.base import session_scope
from supportnova.database.models import (
    AIRun,
    Analysis,
    Complaint,
    ComplaintHistory,
    CustomerResponse,
    Escalation,
    FollowUp,
    Order,
    PolicyReference,
    Resolution,
    Review,
    Role,
    User,
    ValidationCheck,
    ValidationResult,
)
from supportnova.genai_pipeline import context as ctx_builder
from supportnova.genai_pipeline.fault_injection import FaultInjector
from supportnova.genai_pipeline.prompts import PromptTemplate, active_prompt
from supportnova.genai_pipeline.providers import AIRequest, get_provider
from supportnova.genai_pipeline.runner import AttemptRecord, run_stage
from supportnova.genai_pipeline.schemas import (
    ComplaintAnalysis,
    CustomerCommunication,
    constrain_codes,
    provider_schema,
)
from supportnova.knowledge_base.retriever import retrieve
from supportnova.knowledge_base.store import knowledge_service
from supportnova.python_validation.engine import ValidationInput, finalize, run_phase_a, run_phase_b
from supportnova.security import injection
from supportnova.security.pii import redact
from supportnova.security.sanitization import normalize_text
from supportnova.services.history import analyse_history
from supportnova.services.rules import rule_service
from supportnova.services.sla import ensure_sla

log = get_logger(__name__)
STAGES = ["queued", "preprocessing", "retrieval", "ai_analysis", "validation", "response_generation",
          "response_validation", "finalizing", "completed"]


@dataclass
class PipelineOptions:
    trigger: str = "submission"
    fault_profile: str | None = None
    actor_id: int | None = None
    tone: str | None = None
    link_duplicates: bool = True
    auto_assign: bool = True
    classification_override: str | None = None   # reviewer reclassification


def history_event(db: Session, complaint: Complaint, event_type: str, message: str, *, data: dict[str, Any] | None = None,
                  actor: User | None = None, from_status: str | None = None, to_status: str | None = None) -> None:
    db.add(ComplaintHistory(complaint_id=complaint.id, event_type=event_type, message=message[:2000], data=data or {},
                            actor_id=actor.id if actor else None, actor_label=actor.full_name if actor else "SupportNova",
                            from_status=from_status, to_status=to_status))


def set_status(db: Session, complaint: Complaint, status: str, *, actor: User | None = None, note: str = "") -> None:
    if complaint.status == status:
        return
    old = complaint.status
    complaint.status = status
    now = utcnow()
    if status == "Resolved":
        complaint.resolved_at = now
    if status == "Closed":
        complaint.closed_at = now
    history_event(db, complaint, "status.changed", note or f"Status changed from {old} to {status}.", actor=actor,
                  from_status=old, to_status=status)


def _stage(db: Session, complaint: Complaint, stage: str, timings: dict[str, Any]) -> None:
    complaint.processing_stage = stage
    timings.setdefault("_order", []).append(stage)
    analysis_id = timings.get("_analysis_id")
    if analysis_id:
        row = db.get(Analysis, analysis_id)
        if row:
            row.stage_timings = {k: v for k, v in timings.items() if not k.startswith("_")}
    db.commit()


def _log_attempt(db: Session, complaint: Complaint, analysis: Analysis, prompt: PromptTemplate, rec: AttemptRecord, stage: str) -> None:
    db.add(AIRun(complaint_id=complaint.id, analysis_id=analysis.id, stage=stage, attempt=rec.attempt, provider=rec.provider,
                 model=rec.model, prompt_key=prompt.key, prompt_version=prompt.version,
                 request={**rec.request_meta, "prompt_sha256": prompt.sha256}, response_text=rec.response_text,
                 parsed_ok=rec.parsed_ok, error_type=rec.error_type, error_message=rec.error_message, latency_ms=rec.latency_ms,
                 input_tokens=rec.input_tokens, output_tokens=rec.output_tokens, fault_injection=rec.fault_injection))
    db.flush()


def _order_dict(db: Session, ref: str | None) -> tuple[dict[str, Any] | None, bool | None]:
    if not ref:
        return None, None
    row = db.execute(select(Order).where(Order.order_ref == ref.upper())).scalar_one_or_none()
    if row is None:
        return {}, False
    return dict(row.data or {}), True


def _auto_assign(db: Session, complaint: Complaint) -> User | None:
    if not complaint.department_code:
        return None
    from supportnova.database.models import Department
    dept = db.execute(select(Department).where(Department.code == complaint.department_code)).scalar_one_or_none()
    if dept is None:
        return None
    agents = db.execute(select(User).join(Role).where(Role.code == "agent", User.department_id == dept.id, User.is_active)).scalars().all()
    if not agents:
        return None
    load = dict(db.execute(select(Complaint.assigned_agent_id, func.count()).where(
        Complaint.assigned_agent_id.in_([a.id for a in agents]), Complaint.status.notin_(["Resolved", "Closed"]))
        .group_by(Complaint.assigned_agent_id)).tuples().all())
    return min(agents, key=lambda a: (load.get(a.id, 0), a.id))


def process_complaint(complaint_id: int, options: PipelineOptions | None = None) -> dict[str, Any]:
    options = options or PipelineOptions()
    started = time.perf_counter()
    try:
        return _process(complaint_id, options, started)
    except Exception as exc:  # never leave a complaint stuck in Processing
        log.error("pipeline failed", exc_info=True, extra={"complaint": complaint_id})
        with session_scope() as db:
            complaint = db.get(Complaint, complaint_id)
            if complaint is not None:
                complaint.processing_stage = "failed"
                complaint.needs_review = True
                complaint.verification_status = "Manual Review"
                if complaint.status == "Processing":
                    complaint.status = "New"
                history_event(db, complaint, "pipeline.failed", f"Processing failed ({type(exc).__name__}). Sent to manual review.",
                              data={"error": str(exc)[:500]})
                if complaint.source != "evaluation":
                    db.add(Review(complaint_id=complaint.id, status="pending", reason_codes=["pipeline_error"],
                                  reasons=[{"code": "pipeline_error", "name": "Processing error", "detail": str(exc)[:300]}],
                                  original_snapshot={"error": traceback.format_exc()[-2000:]}))
                audit.record(db, action="complaint.processing_failed", entity_type="complaint", entity_id=complaint.complaint_ref,
                             summary=f"Processing error: {type(exc).__name__}", details={"error": str(exc)[:500]})
        return {"ok": False, "error": str(exc)}


def _process(complaint_id: int, options: PipelineOptions, started: float) -> dict[str, Any]:
    settings = get_settings()
    timings: dict[str, Any] = {}
    with session_scope() as db:
        complaint = db.get(Complaint, complaint_id)
        if complaint is None:
            return {"ok": False, "error": "complaint not found"}
        actor = db.get(User, options.actor_id) if options.actor_id else None
        matrix = rule_service.matrix(db)
        as_of: date = (complaint.complaint_date or complaint.created_at or utcnow()).date()
        prev_status = complaint.status
        set_status(db, complaint, "Processing", note=f"Processing started ({options.trigger}).")
        _stage(db, complaint, "preprocessing", timings)

        # ------------------------------------------------------------------ preprocessing
        t = time.perf_counter()
        original = "\n".join([complaint.title, complaint.description, complaint.supporting_info or ""])
        normalized_desc = complaint.description_normalized or normalize_text(complaint.description)
        normalized_full = "\n".join([normalize_text(complaint.title), normalized_desc, normalize_text(complaint.supporting_info or "")])
        report = injection.scan(normalized_full, original=original)
        # fake policy statements: cited policy IDs that do not exist in the knowledge base
        kb = knowledge_service.snapshot(db, matrix, as_of)
        section_keys = {f"{doc}:{sid}" for doc, versions in kb.versions.items() for v in versions for sid in v.sections}
        doc_versions = {doc: {v.version for v in versions} for doc, versions in kb.versions.items()}
        report = injection.with_findings(report, injection.unknown_policy_findings(normalized_full, set(kb.versions), section_keys,
                                                                                   doc_versions))
        complaint.injection_detected = report.is_suspicious
        order, order_found = _order_dict(db, complaint.order_ref)
        customer = complaint.customer
        has_image = any(a.content_type.startswith("image/") for a in complaint.attachments)
        perception = build_perception(
            matrix, title=normalize_text(complaint.title), description=normalized_desc,
            supporting_info=normalize_text(complaint.supporting_info or ""), product_text=complaint.product_text or "",
            order_ref=complaint.order_ref, transaction_ref=complaint.transaction_ref,
            customer_ref=customer.customer_ref if customer else None, customer_type=complaint.customer_type,
            requested_resolution=complaint.requested_resolution, channel=complaint.channel, has_image_attachment=has_image,
            complaint_date=as_of, order=order, order_lookup_attempted=order is not None)
        if order is None and perception.order_ref and not complaint.order_ref:
            order, order_found = _order_dict(db, perception.order_ref)
            if order is not None:
                perception = build_perception(
                    matrix, title=normalize_text(complaint.title), description=normalized_desc,
                    supporting_info=normalize_text(complaint.supporting_info or ""), product_text=complaint.product_text or "",
                    order_ref=perception.order_ref, transaction_ref=complaint.transaction_ref,
                    customer_ref=customer.customer_ref if customer else None, customer_type=complaint.customer_type,
                    requested_resolution=complaint.requested_resolution, channel=complaint.channel, has_image_attachment=has_image,
                    complaint_date=as_of, order=order, order_lookup_attempted=True)
        hist = analyse_history(db, complaint, primary_subcategory=perception.classification.primary,
                               order_ref=perception.order_ref, matrix=matrix, signals=set(perception.signals))
        perception.facts["history"].update({k: hist[k] for k in ("prior_same_issue_count", "unresolved_prior_same_issue",
                                                                 "references_resolved_complaint")})
        complaint.preprocessing = {
            "normalized_text": normalized_full[:6000], "injection": report.to_dict(), "signals": perception.signal_summary(),
            "entities": [asdict(e) for e in perception.entities.entities][:40],
            "classification": perception.classification.to_dict(), "sentiment": asdict(perception.sentiment),
            "facts": perception.facts, "history": hist, "order_found": order_found,
        }
        complaint.product_sku = perception.product_sku
        timings["preprocessing"] = round((time.perf_counter() - t) * 1000)
        dup_of = hist.get("exact_duplicate_of") or hist.get("near_duplicate_of")
        if dup_of and options.link_duplicates and options.trigger in ("submission", "dataset", "evaluation", "lab"):
            original_row = db.execute(select(Complaint).where(Complaint.complaint_ref == dup_of)).scalar_one()
            complaint.is_duplicate = True
            complaint.duplicate_of_id = original_row.id
            complaint.processing_stage = "completed"
            complaint.verification_status = "Pending"
            kind = "exact duplicate" if hist.get("exact_duplicate_of") else f"near-duplicate (similarity {hist.get('near_duplicate_similarity')})"
            history_event(db, complaint, "complaint.duplicate_linked", f"Linked as {kind} of {dup_of}; no second case opened (CHP-POL-01 s7.1).",
                          data={"duplicate_of": dup_of, "kind": kind})
            history_event(db, original_row, "complaint.duplicate_received", f"{complaint.complaint_ref} was linked to this complaint as a {kind}.",
                          data={"duplicate": complaint.complaint_ref})
            set_status(db, complaint, "Closed", note=f"Closed as {kind} of {dup_of}.")
            audit.record(db, action="complaint.duplicate_linked", entity_type="complaint", entity_id=complaint.complaint_ref,
                         summary=f"Linked as {kind} of {dup_of}", actor=actor, details={"history": hist})
            return {"ok": True, "duplicate_of": dup_of}
        if hist.get("repeat_of"):
            complaint.is_repeat = True
            repeat_row = db.execute(select(Complaint).where(Complaint.complaint_ref == hist["repeat_of"])).scalar_one_or_none()
            complaint.repeat_of_id = repeat_row.id if repeat_row else None
        history_event(db, complaint, "pipeline.preprocessed",
                      f"Complaint checked: {len(perception.signals)} risk or intent signal(s), manipulation risk {report.risk_score:.2f}"
                      + (f", repeat of {hist['repeat_of']} ({hist['unresolved_prior_same_issue']} unresolved)" if hist.get("repeat_of") else "") + ".",
                      data={"signals": sorted(perception.signals), "injection": report.to_dict()["types"]})

        # ------------------------------------------------------------------ retrieval
        _stage(db, complaint, "retrieval", timings)
        t = time.perf_counter()
        snapshot = knowledge_service.snapshot(db, matrix, as_of)
        candidates = [c.subcategory for c in perception.classification.candidates[:3]]
        retrieval = retrieve(snapshot, matrix, query=f"{complaint.title}\n{normalized_desc}\n{complaint.product_text or ''}",
                             candidate_subcategories=candidates + perception.classification.secondary, as_of=as_of,
                             top_k=settings.retrieval_top_k)
        timings["retrieval"] = round((time.perf_counter() - t) * 1000)
        history_event(db, complaint, "knowledge.retrieved", f"Found {len(retrieval.evidence)} relevant policy sections"
                      + (f"; {len(retrieval.conflicts)} policy conflict(s) resolved by precedence" if retrieval.conflicts else "") + ".",
                      data={"evidence": [e.ref for e in retrieval.evidence], "conflicts": [c["fact_key"] for c in retrieval.conflicts]})

        # ------------------------------------------------------------------ GenAI analysis
        provider = get_provider()
        version_no = (db.scalar(select(func.max(Analysis.version_no)).where(Analysis.complaint_id == complaint.id)) or 0) + 1
        analysis = Analysis(complaint_id=complaint.id, version_no=version_no, trigger=options.trigger, status="running",
                            provider=provider.name, model=provider.model,
                            fault_injection=options.fault_profile, ruleset_hash=matrix.ruleset_hash)
        db.add(analysis)
        db.flush()
        timings["_analysis_id"] = analysis.id
        _stage(db, complaint, "ai_analysis", timings)
        t = time.perf_counter()
        prompt = active_prompt(db, "complaint_analysis")
        faults = FaultInjector(options.fault_profile) if options.fault_profile else None
        annotated = injection.annotate(normalized_full, report)
        text_for_model = redact(annotated).text
        facts_text = ctx_builder.verified_facts(
            complaint={"complaint_ref": complaint.complaint_ref, "complaint_date": as_of.isoformat(), "channel": complaint.channel,
                       "customer_type": complaint.customer_type},
            customer={"customer_ref": customer.customer_ref} if customer else None, order=order if order_found else None,
            order_ref=perception.order_ref, order_found=order_found, history=hist.get("history", []), matrix=matrix)
        complaint_info = {"title": complaint.title, "product_text": complaint.product_text, "order_ref": complaint.order_ref,
                          "transaction_ref": complaint.transaction_ref, "previous_complaint_ref": complaint.previous_complaint_ref,
                          "requested_resolution": complaint.requested_resolution,
                          "attachments_summary": ", ".join(f"{a.file_name} ({a.content_type})" for a in complaint.attachments)}
        nonce = ctx_builder.new_nonce()
        values = {**ctx_builder.reference_values(matrix, snapshot, as_of), "evidence": ctx_builder.evidence_block(retrieval),
                  "conflicts": ctx_builder.conflicts_block(retrieval), "verified_facts": facts_text,
                  "complaint": ctx_builder.complaint_block(complaint_info, text_for_model), "nonce": nonce,
                  "complaint_id": complaint.complaint_ref}
        system, user = prompt.render(values)
        params = prompt.params or {}
        schema = constrain_codes(provider_schema(prompt.output_schema, inline_refs=provider.name == "gemini"),
                                 ctx_builder.catalog(matrix, snapshot))
        request = AIRequest(stage="analysis", system=system, user=user, schema_name=prompt.output_schema, json_schema=schema,
                            temperature=float(params.get("temperature", settings.ai_temperature)),
                            max_output_tokens=int(params.get("max_output_tokens", settings.ai_max_output_tokens)),
                            timeout_seconds=settings.ai_timeout_seconds)
        result = run_stage(provider, request, max_attempts=1 + max(0, settings.ai_max_retries), faults=faults,
                           on_attempt=lambda rec: _log_attempt(db, complaint, analysis, prompt, rec, "analysis"))
        ai: ComplaintAnalysis | None = result.output  # type: ignore[assignment]
        ai_data = result.data
        if ai is not None and faults and ai_data is not None:
            ai_data = faults.mutate_analysis(ai_data)
            ai = ComplaintAnalysis.model_validate(ai_data)
        timings["ai_analysis"] = round((time.perf_counter() - t) * 1000)
        history_event(db, complaint, "ai.analysis_completed" if ai else "ai.analysis_failed",
                      (f"AI analysis by {provider.name}/{provider.model} "
                       f"(prompt {prompt.key} v{prompt.version}), {len(result.attempts)} attempt(s)")
                      + ("." if ai else f"; no usable answer ({(result.error or 'unknown error').rstrip('.')})."),
                      data={"attempts": len(result.attempts), "provider": provider.name, "model": provider.model,
                            "fault_injection": options.fault_profile})

        # ------------------------------------------------------------------ Python validation (Phase A)
        _stage(db, complaint, "validation", timings)
        t = time.perf_counter()
        vinp = ValidationInput(matrix=matrix, snapshot=snapshot, as_of=as_of, complaint_ref=complaint.complaint_ref,
                               complaint={"title": complaint.title, "product_text": complaint.product_text or ""},
                               perception=perception, injection=report.to_dict(), retrieval=retrieval, ai=ai,
                               ai_error=result.error, facts_text=facts_text)
        phase = run_phase_a(vinp, override_subcategory=options.classification_override)
        timings["validation"] = round((time.perf_counter() - t) * 1000)

        # ------------------------------------------------------------------ GenAI communication (from the validated decision)
        _stage(db, complaint, "response_generation", timings)
        t = time.perf_counter()
        comm_prompt = active_prompt(db, "customer_communication")
        validated = phase.validated
        tone = options.tone or complaint.requested_tone or "professional"
        customer_name = (customer.full_name.split()[0] if customer and customer.full_name else "Customer")
        cited_ids = {r.evidence_id for r in (ai.policy_references if ai else []) if r.evidence_id}
        applicable_ids = {a["evidence_id"] for a in phase.applicability if a["applicability"] == "Applicable" and a["evidence_id"]}
        comm_values = {"tone": tone, "customer_name": customer_name,
                       "decision": ctx_builder.decision_block(validated, matrix),
                       "timelines": "\n".join(f"- {x['text']}" for x in validated["timelines"]) or "- (no timelines may be quoted)",
                       "questions": "\n".join(f"- {q}" for q in validated["clarification_questions"]) or "- none",
                       "follow_up": (f"{validated['follow_up'].get('type')} due in {validated['follow_up'].get('due_hours')} hours"
                                     if validated["follow_up"].get("required") else "none"),
                       "evidence": ctx_builder.evidence_block(retrieval, only=(cited_ids | applicable_ids) or None),
                       "complaint": ctx_builder.complaint_block(complaint_info, text_for_model), "nonce": ctx_builder.new_nonce(),
                       "complaint_id": complaint.complaint_ref}
        c_system, c_user = comm_prompt.render(comm_values)
        c_params = comm_prompt.params or {}
        c_request = AIRequest(stage="communication", system=c_system, user=c_user, schema_name=comm_prompt.output_schema,
                              json_schema=provider_schema(comm_prompt.output_schema, inline_refs=provider.name == "gemini"),
                              temperature=float(c_params.get("temperature", 0.3)),
                              max_output_tokens=int(c_params.get("max_output_tokens", 2500)),
                              timeout_seconds=settings.ai_timeout_seconds)
        c_result = run_stage(provider, c_request, max_attempts=1 + max(0, settings.ai_max_retries), faults=faults,
                             on_attempt=lambda rec: _log_attempt(db, complaint, analysis, comm_prompt, rec, "communication"))
        comm: CustomerCommunication | None = c_result.output  # type: ignore[assignment]
        comm_data = c_result.data
        if comm is not None and faults and comm_data is not None:
            comm_data = faults.mutate_communication(comm_data)
            comm = CustomerCommunication.model_validate(comm_data)
        timings["response_generation"] = round((time.perf_counter() - t) * 1000)
        _stage(db, complaint, "response_validation", timings)
        t = time.perf_counter()
        checks_b = run_phase_b(vinp, phase, comm, requested_tone=tone, comm_error=c_result.error)
        verification = finalize(vinp, phase, checks_b)
        timings["response_validation"] = round((time.perf_counter() - t) * 1000)

        # ------------------------------------------------------------------ persistence
        _stage(db, complaint, "finalizing", timings)
        now = utcnow()
        decision = phase.decision
        analysis.status = "completed" if ai else "invalid_output"
        analysis.output = ai_data if ai else None
        analysis.communication = comm_data if comm else None
        analysis.error = None if ai else result.error
        analysis.prompt_versions = {"analysis": {"key": prompt.key, "version": prompt.version, "sha256": prompt.sha256},
                                    "communication": {"key": comm_prompt.key, "version": comm_prompt.version, "sha256": comm_prompt.sha256}}
        analysis.policy_versions = {e.doc_id: e.version for e in retrieval.evidence}
        retrieval_dict = retrieval.to_dict()
        analysis.retrieval = retrieval_dict
        analysis.completed_at = now
        analysis.total_latency_ms = round((time.perf_counter() - started) * 1000)
        timings["total"] = analysis.total_latency_ms
        analysis.stage_timings = {k: v for k, v in timings.items() if not k.startswith("_")}
        for app in phase.applicability:
            db.add(PolicyReference(analysis_id=analysis.id, doc_id=app["doc_id"], version=app["version"], section_id=app["section_id"],
                                   chunk_uid=next((e.chunk_uid for e in retrieval.evidence if e.evidence_id == app["evidence_id"]), None),
                                   cited_by="retrieval", applicability=app["applicability"],
                                   is_active_version=app["applicability"] != "Outdated", valid=True, note=app["reason"]))
        for cit in (ai.policy_references if ai else []):
            info = snapshot.resolve_ref(f"{cit.policy_id}:{cit.section}", as_of)
            db.add(PolicyReference(analysis_id=analysis.id, doc_id=cit.policy_id[:32], version=info.get("active_version"),
                                   section_id=cit.section[:32], cited_by="ai", applicability=cit.applicability,
                                   is_active_version=bool(info.get("active_version")), valid=bool(info["doc_exists"] and info["section_exists"]),
                                   note=cit.reason[:500]))
        for ref in decision.policy_refs:
            doc_id, _, sec = ref.partition(":")
            active = snapshot.active_version(doc_id, as_of)
            db.add(PolicyReference(analysis_id=analysis.id, doc_id=doc_id, version=active.version if active else None,
                                   section_id=sec, cited_by="rule",
                                   applicability="Applicable", is_active_version=True, valid=True,
                                   note=f"Required by {decision.selected_rule_id}"))
        vr = ValidationResult(analysis_id=analysis.id, complaint_id=complaint.id, overall_status=verification.overall_status,
                              verification_score=verification.score, decision=verification.decision,
                              dimension_scores=verification.dimension_scores, python_expected=decision.to_dict(),
                              comparison=phase.comparison, validated_decision=validated, review_reasons=verification.review_reasons,
                              counts=verification.counts, ruleset_hash=matrix.ruleset_hash)
        db.add(vr)
        db.flush()
        for ch in phase.checks + checks_b:
            db.add(ValidationCheck(result_id=vr.id, code=ch.code, name=ch.name, dimension=ch.dimension, severity=ch.severity,
                                   status=ch.status, message=ch.message[:4000], expected=_jsonable(ch.expected),
                                   actual=_jsonable(ch.actual), rule_refs=ch.rule_refs, policy_refs=ch.policy_refs))
        db.add(Resolution(complaint_id=complaint.id, analysis_id=analysis.id,
                          ai_steps=[s.model_dump() for s in ai.resolution_steps] if ai else [],
                          validated_steps=validated["resolution_steps"],
                          eligibility={"ai": {"refund": ai.refund_eligibility.model_dump(), "replacement": ai.replacement_eligibility.model_dump(),
                                              "compensation": ai.compensation_eligibility.model_dump()} if ai else None,
                                       "validated": validated["eligibility"]},
                          status="validated" if verification.decision == "Verified" else "proposed"))
        rsp_fail = any(ch.status == "fail" for ch in checks_b if ch.code.startswith(("RSP", "SEC")))
        if comm is not None:
            db.add(CustomerResponse(complaint_id=complaint.id, analysis_id=analysis.id, version_no=version_no, kind="response",
                                    tone=tone, subject=comm.subject[:240], body=comm.customer_response, source=provider.name,
                                    status="ready" if (verification.decision == "Verified" and not rsp_fail) else "requires_review",
                                    validation={"checks": [asdict(ch) for ch in checks_b], "follow_up_message": comm.follow_up_message}))
        if decision.escalation.required:
            open_esc = db.execute(select(Escalation).where(Escalation.complaint_id == complaint.id, Escalation.status == "open")).scalars().first()
            if open_esc is None or open_esc.rank < decision.escalation.rank:
                db.add(Escalation(complaint_id=complaint.id, level=decision.escalation.level, rank=decision.escalation.rank,
                                  reason="; ".join(f.reason for f in decision.escalation.fired[:4]),
                                  source="rule" if not (ai and ai.escalation_required) else "rule+ai",
                                  rule_ids=[f.rule_id for f in decision.escalation.fired], departments=decision.escalation.departments,
                                  notes=validated["escalation"]["notes"] or {}, status="open"))
                history_event(db, complaint, "escalation.created", f"Escalated to {decision.escalation.level} by "
                              + ", ".join(f.rule_id for f in decision.escalation.fired[:4])
                              + ("" if (ai and ai.escalation_required) else "; the AI missed it, the rules require it") + ".")
        fu = decision.follow_up
        if fu.get("required") and fu.get("due_hours") is not None:
            db.add(FollowUp(complaint_id=complaint.id, type=fu.get("type") or "Resolution confirmation",
                            message=(comm.follow_up_message if comm and comm.follow_up_message else f"{fu.get('type')} for {complaint.complaint_ref}."),
                            due_at=now + timedelta(hours=float(fu["due_hours"])), status="scheduled", source_rule=fu.get("source_rule")))
        # denormalised final intelligence
        complaint.category_code = decision.primary_category
        complaint.subcategory_code = decision.primary_subcategory
        complaint.department_code = decision.department
        complaint.urgency, complaint.priority = decision.urgency, decision.priority
        complaint.sentiment = ai.sentiment if ai else perception.sentiment.label
        complaint.escalation_level = decision.escalation.level
        complaint.escalation_required = decision.escalation.required
        complaint.verification_score = verification.score
        complaint.verification_status = verification.decision
        complaint.needs_review = verification.decision == "Manual Review"
        complaint.ai_python_agreement = bool(ai and ai.issue_category == decision.primary_category and ai.department == decision.department
                                             and ai.escalation_required == decision.escalation.required)
        complaint.analyzed_at = now
        ensure_sla(db, complaint, decision.priority, matrix)
        if verification.decision == "Manual Review" and complaint.source != "evaluation":  # evaluation runs never fill the queue
            pending = db.execute(select(Review).where(Review.complaint_id == complaint.id, Review.status.in_(["pending", "in_review"]))).scalars().first()
            if pending is None:
                db.add(Review(complaint_id=complaint.id, analysis_id=analysis.id, validation_result_id=vr.id, status="pending",
                              reason_codes=[r["code"] for r in verification.review_reasons], reasons=verification.review_reasons,
                              priority=decision.priority,
                              original_snapshot={"ai_output": ai_data, "validated_decision": validated, "score": verification.score}))
                history_event(db, complaint, "review.queued", "Sent to manual review: "
                              + "; ".join(r["name"] for r in verification.review_reasons[:4]) + ".")
        target = "Escalated" if decision.escalation.required else "Analyzed"
        if prev_status in ("Reopened",) and target == "Analyzed":
            target = "In Progress"
        set_status(db, complaint, target, note=f"Analysis complete: {verification.decision} ({verification.score:g}/100).")
        if options.auto_assign and complaint.assigned_agent_id is None:
            agent = _auto_assign(db, complaint)
            if agent is not None:
                complaint.assigned_agent_id = agent.id
                history_event(db, complaint, "complaint.assigned", f"Auto-assigned to {agent.full_name} ({complaint.department_code}).")
                if complaint.status == "Analyzed":
                    set_status(db, complaint, "Assigned", note=f"Assigned to {agent.full_name}.")
        history_event(db, complaint, "validation.completed",
                      f"Rule check: {verification.decision}, score {verification.score:g}/100 "
                      f"({verification.counts.get('fail', 0)} failed, {verification.counts.get('warn', 0)} warnings).",
                      data={"score": verification.score, "decision": verification.decision,
                            "failed": [ch.code for ch in phase.checks + checks_b if ch.status == "fail"]})
        complaint.processing_stage = "completed"
        audit.record(db, action="complaint.processed", entity_type="complaint", entity_id=complaint.complaint_ref, actor=actor,
                     summary=f"Processed ({options.trigger}): {provider.name}/{provider.model} -> {verification.decision} {verification.score:g}",
                     details={"analysis_id": analysis.id, "provider": provider.name, "model": provider.model,
                              "prompt_versions": analysis.prompt_versions, "policy_versions": analysis.policy_versions,
                              "ruleset_hash": matrix.ruleset_hash, "fault_injection": options.fault_profile,
                              "ai_attempts": len(result.attempts) + len(c_result.attempts), "decision": verification.decision,
                              "score": verification.score, "review_reasons": [r["code"] for r in verification.review_reasons],
                              "timings_ms": analysis.stage_timings})
        return {"ok": True, "analysis_id": analysis.id, "decision": verification.decision, "score": verification.score,
                "timings": analysis.stage_timings}


def _jsonable(value: Any) -> Any:
    import json

    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))
