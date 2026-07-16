from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api import scan_status
from api.agents.pentest_agent import scan as run_scan
from api.schemas import (
    ScanProgressResponse,
    ScanRequest,
    ScanResponse,
    SelfAttestRequest,
    TargetStatusRequest,
    TargetStatusResponse,
    VerifyTargetRequest,
    VerifyTargetResponse,
)
from api.scope import (
    ScopeDenied,
    effective_status,
    get_or_create_target,
    get_target_status,
    verify_file_token,
    verify_self_attestation,
)
from memory.db import get_session
from memory.repository import save_findings_for_target

router = APIRouter(prefix="/v1", tags=["scan"])


@router.post("/targets/verify", response_model=VerifyTargetResponse)
def verify_target(req: VerifyTargetRequest, session: Session = Depends(get_session)) -> VerifyTargetResponse:
    try:
        target = verify_file_token(session, req.target, req.token)
    except ScopeDenied as exc:
        return VerifyTargetResponse(status="unverified", error=str(exc))
    return VerifyTargetResponse(status=target.status, verification_method=target.verification_method)


@router.post("/targets/status", response_model=TargetStatusResponse)
def target_status(req: TargetStatusRequest, session: Session = Depends(get_session)) -> TargetStatusResponse:
    target = get_target_status(session, req.target)
    return TargetStatusResponse(
        # effective_status(), not target.status directly — the DB column
        # never flips back on its own when a TTL passes, so reading it raw
        # here would tell the CLI a stale "verified" target is still good,
        # skip re-attesting, and then have every stage get denied anyway.
        status=effective_status(target),
        verification_method=target.verification_method,
        expires_at=target.expires_at.isoformat() if target.expires_at else None,
    )


@router.post("/targets/self-attest", response_model=VerifyTargetResponse)
def self_attest(req: SelfAttestRequest, session: Session = Depends(get_session)) -> VerifyTargetResponse:
    target = verify_self_attestation(session, req.target, req.statement)
    return VerifyTargetResponse(status=target.status, verification_method=target.verification_method)


@router.get("/scan/progress", response_model=ScanProgressResponse)
def scan_progress(target: str) -> ScanProgressResponse:
    info = scan_status.get(target)
    if info is None:
        return ScanProgressResponse(running=False)
    return ScanProgressResponse(
        running=True,
        stage=info["stage"],
        stage_index=info["index"],
        stage_total=info["total"],
        elapsed_seconds=round(info["elapsed_seconds"], 1),
    )


@router.post("/scan", response_model=ScanResponse)
def scan_target(req: ScanRequest, session: Session = Depends(get_session)) -> ScanResponse:
    result = run_scan(session, req.target)

    try:
        target_row = get_or_create_target(session, req.target)
        save_findings_for_target(session, target_row, result["findings"])
    except Exception as exc:  # noqa: BLE001 - Memory being down shouldn't hide scan results
        session.rollback()
        result["warnings"].append(f"findings were not persisted to Memory: {exc}")

    return ScanResponse(findings=result["findings"], warnings=result["warnings"], summary=result["summary"])
