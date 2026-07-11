from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.agents.pentest_agent import scan as run_scan
from api.schemas import ScanRequest, ScanResponse, VerifyTargetRequest, VerifyTargetResponse
from api.scope import ScopeDenied, get_or_create_target, verify_file_token
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
