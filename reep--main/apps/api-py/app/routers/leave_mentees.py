"""Student leave, the two reads the screens need (2026-11-05).

    GET /api/leaves/mine/approver   who decides MY leave (the student's header)
    GET /api/leaves/mentees         the mentor's queue: their mentees' requests

ITS OWN MODULE, as `leave_paper.py` and `leave_attachments.py` are, so
`routers/leave.py` keeps the submit/decide lifecycle and these two reads do
not grow it. Nothing here writes: a student submits and withdraws through
`POST /leaves` and `/cancel`, a mentor decides through `/decision`, and the
supporting document travels through the attachment endpoints — all of which
already existed and are reused unchanged.

The routing rule (whose request is the mentor's) is `app/student_leave.py`'s,
imported and never restated here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..governance import require_capability
from ..identity import get_current_session
from ..models.leave import LeaveRequest, LeaveStatus
from ..models.leave_attachment import LeaveAttachment
from ..models.user import Student, User
from ..student_leave import (
    ROUTED_TO_MENTOR,
    ROUTED_TO_OFFICE,
    applicants_mentored_by,
    assigned_mentor_user_id,
)
from .leave import MENTEES_CAPABILITY, LeaveOut, _leave_out
from .mentor import require_mentor

router = APIRouter(prefix="/leaves", tags=["leaves"])


# --------------------------------------------------------------------------- #
# The student's header: who decides my leave
# --------------------------------------------------------------------------- #


class LeaveRouteOut(BaseModel):
    """The header of the student's My leave screen: who they are, and who will
    decide what they send. Every field but `name` and `routed_to` may be None."""

    name: str
    usn: str | None
    course: str | None
    #: The mentor's name when `routed_to` is MENTOR, else None.
    mentor_name: str | None
    #: MENTOR or OFFICE. The form's button says where the request will go.
    routed_to: str


def _course_line(db: Session, stu: Student) -> str | None:
    """"General MBA · Finance", read through the spine as the profile card is."""
    # Imported here: `routers.student` is a large module that imports a great
    # deal, and this one helper is all this module needs from it.
    from .student import _institution_for

    place = _institution_for(db, stu)
    return " · ".join(p for p in (place.course_name, place.specialization_name) if p) or None


@router.get("/mine/approver", response_model=LeaveRouteOut)
def my_leave_route(
    session: dict = Depends(get_current_session), db: Session = Depends(get_db)
) -> LeaveRouteOut:
    """Who decides MY leave. The applicant's own read, open to every account
    like `/mine`; it names only the caller's own mentor."""
    uid = session["userId"]
    me = db.get(User, uid)
    stu = db.scalar(select(Student).where(Student.user_id == uid))
    mentor_uid = assigned_mentor_user_id(db, uid)
    mentor = db.get(User, mentor_uid) if mentor_uid else None
    return LeaveRouteOut(
        name=me.name if me else "",
        usn=stu.usn if stu else None,
        course=_course_line(db, stu) if stu else None,
        mentor_name=mentor.name if mentor else None,
        routed_to=ROUTED_TO_MENTOR if mentor else ROUTED_TO_OFFICE,
    )


# --------------------------------------------------------------------------- #
# The mentor's queue
# --------------------------------------------------------------------------- #


class LeaveFileBrief(BaseModel):
    """One supporting document: enough to name it and fetch it through
    `GET /leaves/{id}/attachments/{attachment_id}/file`."""

    id: str
    original_name: str


class MenteeLeaveOut(LeaveOut):
    """A mentee's request as their mentor reads it: the applicant's full
    projection (the mentor decides it, so they read the reason, as the office
    does for faculty), plus the USN the queue prints under the name and the
    documents attached to it."""

    requester_usn: str | None = None
    attachments: list[LeaveFileBrief] = Field(default_factory=list)


#: The tabs of the mentor's queue. PENDING is the default and includes a
#: legacy FIRST_APPROVED row, as the office's `/pending` does.
MENTEE_QUEUE_STATUSES: dict[str, tuple[LeaveStatus, ...]] = {
    "PENDING": (LeaveStatus.SUBMITTED, LeaveStatus.FIRST_APPROVED),
    "APPROVED": (LeaveStatus.APPROVED,),
    "REJECTED": (LeaveStatus.REJECTED,),
    "CANCELLED": (LeaveStatus.CANCELLED,),
    "REVOKED": (LeaveStatus.REVOKED,),
}


def _usns(db: Session, user_ids: set[str]) -> dict[str, str | None]:
    rows = db.execute(select(Student.user_id, Student.usn).where(Student.user_id.in_(user_ids)))
    return dict(rows.all())


def _files(db: Session, leave_ids: list[str]) -> dict[str, list[LeaveFileBrief]]:
    found: dict[str, list[LeaveFileBrief]] = {}
    rows = db.scalars(
        select(LeaveAttachment)
        .where(LeaveAttachment.leave_request_id.in_(leave_ids))
        .order_by(LeaveAttachment.uploaded_at)
    )
    for att in rows:
        found.setdefault(att.leave_request_id, []).append(
            LeaveFileBrief(id=att.id, original_name=att.original_name)
        )
    return found


@router.get("/mentees", response_model=list[MenteeLeaveOut])
def mentee_leaves(
    status_filter: str = Query(
        default="PENDING",
        alias="status",
        description="PENDING (default), APPROVED, REJECTED, CANCELLED or REVOKED.",
    ),
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[MenteeLeaveOut]:
    """Leave requests from THIS mentor's mentees and nobody else's.

    Gated on `mentor.mentees`, which a faculty account holds by having a
    mentee, so a faculty member with nobody assigned gets the role's 403
    rather than an empty list that reads as "no requests". The Main Admin does
    not hold it either: a mentored student's leave is the mentor's alone.

    Pending oldest first (the order to work through them); the other tabs
    newest first.
    """
    require_mentor(session)
    require_capability(db, session, MENTEES_CAPABILITY)
    tab = status_filter.upper()
    wanted = MENTEE_QUEUE_STATUSES.get(tab)
    if wanted is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="status must be one of " + ", ".join(MENTEE_QUEUE_STATUSES) + ".",
        )
    query = select(LeaveRequest).where(
        LeaveRequest.requester_user_id.in_(applicants_mentored_by(session["userId"])),
        LeaveRequest.status.in_(wanted),
    )
    if tab == "PENDING":
        query = query.order_by(LeaveRequest.created_at)
    else:
        query = query.order_by(
            func.coalesce(
                LeaveRequest.cancelled_at,
                LeaveRequest.decision_changed_at,
                LeaveRequest.second_decided_at,
                LeaveRequest.first_decided_at,
            ).desc(),
            LeaveRequest.created_at.desc(),
        ).limit(200)
    rows = db.scalars(query).all()
    if not rows:
        return []
    usns = _usns(db, {lr.requester_user_id for lr in rows})
    files = _files(db, [lr.id for lr in rows])
    return [
        MenteeLeaveOut(
            **_leave_out(lr, db).model_dump(),
            requester_usn=usns.get(lr.requester_user_id),
            attachments=files.get(lr.id, []),
        )
        for lr in rows
    ]
