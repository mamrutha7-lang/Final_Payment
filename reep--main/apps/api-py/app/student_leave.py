"""Who decides a STUDENT's leave request (2026-11-05, the owner's decision).

A student's leave goes to THEIR MENTOR, and only their mentor decides it. A
student with no mentor goes to the office's queue (the Main Admin, and anybody
the office granted `admin.leave_approvals`), exactly as every request did
before this date. Faculty leave is unchanged: the office decides it.

THE ROUTE IS READ, NEVER STORED. Nothing on `leave_requests` says "this one is
the mentor's". It is answered from `students.mentor_id` every time it is asked,
so a pending request follows the student when the office moves them to another
mentor on Assign faculty, and falls back to the office when they are released.
A stored pointer would leave the request with a mentor who no longer mentors
the student, and the five places that set `students.mentor_id` would each have
to remember to move it.

A MENTOR WHOSE ACCOUNT IS DISABLED OR REMOVED DOES NOT COUNT. Disabling a
faculty account releases their mentees already; a REMOVED one keeps the
pointer (so Restore is exact), and a removed account cannot sign in to decide
anything. Both send the request to the office instead of leaving it stuck.

WHAT A STUDENT MAY SUBMIT is here too (`student_submit_refusal`, and
`DOCUMENT_REQUIRED_KINDS` for the types that need a document), so the router
that takes the form only asks "is there a reason to refuse this?" and never
learns the rules.

ONE QUERY, THREE READERS. `_routes()` is the only place the rule is written:
`assigned_mentor_user_id` (the decision gate), `mentor_routed_applicants`
(what the office's queues leave out) and `applicants_mentored_by` (the
mentor's own queue) all read it, so the gate and the two lists cannot disagree
about whose request is whose.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from .leave_policy import overlapping_request
from .models.user import Mentor, Role, Student, User

#: What a student may apply for. MEDICAL is not one of the five options printed
#: on the college's own paper form (`models.leave_policy.PRINTED_LEAVE_KINDS`),
#: so it is accepted at the API and kept out of that tuple: adding it there
#: would also widen the leave-balance CHECK and ask the paper renderer to strike
#: through an option the form does not print.
STUDENT_LEAVE_KINDS: Final[tuple[str, ...]] = ("MEDICAL", "CASUAL", "OOD")

#: The types a student cannot send without a supporting document (2026-11-11,
#: the owner's decision: a medical leave comes with its certificate). The
#: request and the file arrive together through `POST /leaves/student`, so a
#: request of one of these types never exists without its document; the JSON
#: `POST /leaves` refuses a student's request of these types, and a pending
#: one's last document cannot be removed.
DOCUMENT_REQUIRED_KINDS: Final[tuple[str, ...]] = ("MEDICAL",)

#: Said when a student's request of a `DOCUMENT_REQUIRED_KINDS` type arrives
#: without its document.
DOCUMENT_REQUIRED_MESSAGE: Final = (
    "Medical leave needs a supporting document. Upload your medical "
    "certificate (PDF, PNG or JPG) and send the request again."
)

#: Said when somebody tries to remove the only document on a pending request
#: of a `DOCUMENT_REQUIRED_KINDS` type.
LAST_DOCUMENT_MESSAGE: Final = (
    "A medical leave request must keep its supporting document while it is "
    "pending. Upload the replacement first, then remove this one, or "
    "withdraw the request."
)


def document_required(leave_kind: str | None) -> bool:
    """Must a student's request of this type carry a supporting document?"""
    return leave_kind in DOCUMENT_REQUIRED_KINDS

ROUTED_TO_MENTOR: Final = "MENTOR"
ROUTED_TO_OFFICE: Final = "OFFICE"


def _routes() -> Select:
    """(applicant user id, mentor user id) for every STUDENT whose mentor can
    decide their leave right now."""
    applicant = aliased(User)
    mentor_user = aliased(User)
    return (
        select(
            Student.user_id.label("applicant_user_id"),
            Mentor.user_id.label("mentor_user_id"),
        )
        .join(Mentor, Mentor.id == Student.mentor_id)
        .join(applicant, applicant.id == Student.user_id)
        .join(mentor_user, mentor_user.id == Mentor.user_id)
        .where(
            applicant.role == Role.STUDENT,
            mentor_user.deleted_at.is_(None),
            mentor_user.disabled_at.is_(None),
        )
    )


def assigned_mentor_user_id(db: Session, applicant_user_id: str) -> str | None:
    """The account that decides this applicant's leave, or None when it is the
    office's (a faculty applicant, or a student with no active mentor)."""
    routes = _routes().subquery()
    return db.scalar(
        select(routes.c.mentor_user_id).where(routes.c.applicant_user_id == applicant_user_id)
    )


def mentor_routed_applicants() -> Select:
    """Every applicant whose leave is a mentor's, as a subquery for `NOT IN`."""
    routes = _routes().subquery()
    return select(routes.c.applicant_user_id)


def applicants_mentored_by(mentor_user_id: str) -> Select:
    """The applicants whose leave this account decides, as a subquery for `IN`."""
    routes = _routes().subquery()
    return select(routes.c.applicant_user_id).where(routes.c.mentor_user_id == mentor_user_id)


def student_submit_refusal(
    db: Session,
    *,
    user_id: str,
    leave_kind: str | None,
    from_date: date,
    to_date: date,
) -> str | None:
    """The sentence a STUDENT's request is refused with, or None.

    The leave type is required and is one of `STUDENT_LEAVE_KINDS`: the staff
    options (permission, restricted holiday, loss of pay) are about a staff
    contract a student does not have.

    And no two live requests for the same day. `leave_policy.submit_refusal`
    checks overlap only once the office has recorded an allowance, so a staff
    form nobody configured keeps accepting what it accepted yesterday.
    Students have no allowance table at all, and a mentor asked to approve the
    same Tuesday twice should never see it.
    """
    if leave_kind not in STUDENT_LEAVE_KINDS:
        return "Choose the type of leave: Medical, Casual or On official duty."
    clash = overlapping_request(db, user_id, from_date, to_date)
    if clash is not None:
        return (
            "You already have a leave request covering "
            f"{clash.from_date.isoformat()} to {clash.to_date.isoformat()}, which overlaps "
            "these days. Withdraw that request first if you want to apply again."
        )
    return None

