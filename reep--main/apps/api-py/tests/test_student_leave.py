"""A student's leave goes to their mentor, and only their mentor decides it
(2026-11-05, the owner's decision).

What this module holds down:

1. A STUDENT WITH AN ACTIVE MENTOR: the mentor sees the request in
   `GET /leaves/mentees`, decides it through the ordinary `/decision`, and
   signs as MENTOR. Another mentor, the Main Admin and a delegate of the
   office are all refused with the 404 an invented id gets, and the office's
   queues do not list it.
2. A STUDENT WITH NO MENTOR: the request is the office's, exactly as before.
3. THE ROUTE FOLLOWS THE STUDENT. Moving a student to another mentor moves
   their pending request with them; it is read from `students.mentor_id`,
   never stored on the request.
4. THE STUDENT'S FORM: a leave type is required and is Medical, Casual or On
   official duty; two live requests for one day are refused; the student
   withdraws their own pending request; the supporting document reaches the
   mentor.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from conftest import APPLICATION_CV, requires_db

from app.db import SessionLocal
from app.models.leave import LeaveRequest
from app.models.user import Mentor, Role, Student, User

LEAVES = "/api/leaves"
APPROVE = {"decision": "APPROVE", "note": None}


def _student_id(user_id: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(Student.id).where(Student.user_id == user_id))


def _seat(student_user_id: str, mentor_user_id: str) -> None:
    """Make `mentor_user_id` this student's mentor, creating their group the
    first time, as Assign faculty does."""
    with SessionLocal() as db:
        group = db.scalar(select(Mentor).where(Mentor.user_id == mentor_user_id))
        if group is None:
            group = Mentor(user_id=mentor_user_id)
            db.add(group)
            db.flush()
        db.scalar(select(Student).where(Student.user_id == student_user_id)).mentor_id = group.id
        db.commit()


def _unseat(student_user_id: str) -> None:
    with SessionLocal() as db:
        db.scalar(select(Student).where(Student.user_id == student_user_id)).mentor_id = None
        db.commit()


def _submit(client, headers, **extra) -> dict:
    body = {
        "from_date": "2026-12-14",
        "to_date": "2026-12-15",
        "reason": "Fever, the doctor advised two days of rest.",
        "leave_kind": "MEDICAL",
    }
    body.update(extra)
    r = client.post(LEAVES, headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()}


@pytest.fixture
def people(make_user):
    """A student, their mentor, another mentor (with a mentee of their own, so
    they hold `mentor.mentees`), and the Main Admin."""
    student = make_user("sl-stu", Role.STUDENT)
    mentor = make_user("sl-men", Role.MENTOR)
    other = make_user("sl-oth", Role.MENTOR)
    others_mentee = make_user("sl-om", Role.STUDENT)
    office = make_user("sl-adm", Role.ADMIN)
    _seat(student.user_id, mentor.user_id)
    _seat(others_mentee.user_id, other.user_id)
    yield {"student": student, "mentor": mentor, "other": other, "office": office}
    with SessionLocal() as db:
        db.execute(
            delete(LeaveRequest).where(
                LeaveRequest.requester_user_id.in_([student.user_id, others_mentee.user_id])
            )
        )
        db.commit()


@requires_db
def test_the_mentor_decides_their_mentees_leave_and_nobody_else_can(client, people):
    student, mentor, other, office = (
        people["student"], people["mentor"], people["other"], people["office"]
    )
    leave_id = _submit(client, student.headers)["id"]

    # The mentor's queue has it; the other mentor's and the office's do not.
    assert leave_id in _ids(client.get(f"{LEAVES}/mentees", headers=mentor.headers))
    assert leave_id not in _ids(client.get(f"{LEAVES}/mentees", headers=other.headers))
    assert leave_id not in _ids(client.get(f"{LEAVES}/pending", headers=office.headers))

    # Everybody but the mentor gets the answer an invented id gets.
    invented = client.post(f"{LEAVES}/no-such-leave/decision", headers=other.headers, json=APPROVE)
    for headers in (other.headers, office.headers):
        refused = client.post(f"{LEAVES}/{leave_id}/decision", headers=headers, json=APPROVE)
        assert refused.status_code == 404, refused.text
        assert refused.json() == invented.json()
    # Nor may the office change a decision on it, or read its paper.
    assert client.post(
        f"{LEAVES}/{leave_id}/change-decision",
        headers=office.headers,
        json={"action": "REVOKE", "reason": "testing"},
    ).status_code == 404
    assert client.get(f"{LEAVES}/{leave_id}/paper.pdf", headers=office.headers).status_code == 404

    done = client.post(f"{LEAVES}/{leave_id}/decision", headers=mentor.headers, json=APPROVE)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "APPROVED"
    assert done.json()["first_signed_as"] == "MENTOR"
    assert done.json()["director_name"] == "Voice Test sl-men"

    assert leave_id not in _ids(client.get(f"{LEAVES}/mentees", headers=mentor.headers))
    assert leave_id in _ids(
        client.get(f"{LEAVES}/mentees", params={"status": "APPROVED"}, headers=mentor.headers)
    )
    mine = client.get(f"{LEAVES}/mine", headers=student.headers).json()
    assert [row["status"] for row in mine if row["id"] == leave_id] == ["APPROVED"]


@requires_db
def test_the_mentor_rejects_with_a_reason_the_student_reads(client, people):
    """A rejection needs a reason (2026-11-06): none, or only spaces, is a 422
    and the request stays pending; with one, the student reads it on
    `/leaves/mine`."""
    student, mentor = people["student"], people["mentor"]
    leave_id = _submit(client, student.headers, leave_kind="CASUAL")["id"]
    url = f"{LEAVES}/{leave_id}/decision"

    for body in ({"decision": "REJECT"}, {"decision": "REJECT", "note": "   "}):
        refused = client.post(url, headers=mentor.headers, json=body)
        assert refused.status_code == 422, refused.text
        assert "reason" in refused.json()["detail"]
    assert leave_id in _ids(client.get(f"{LEAVES}/mentees", headers=mentor.headers))

    reason = "Internal exam on these dates; apply for the following week."
    r = client.post(url, headers=mentor.headers, json={"decision": "REJECT", "note": reason})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJECTED"
    mine = client.get(f"{LEAVES}/mine", headers=student.headers).json()
    assert [row["director_note"] for row in mine if row["id"] == leave_id] == [reason]

    # Deciding it again is still the "already decided" 409, note or not.
    again = client.post(url, headers=mentor.headers, json={"decision": "REJECT"})
    assert again.status_code == 409, again.text


@requires_db
def test_an_approval_note_is_optional_and_reaches_the_student(client, people):
    student, mentor = people["student"], people["mentor"]
    leave_id = _submit(client, student.headers, leave_kind="MEDICAL")["id"]
    note = "Bring the medical certificate when you return."
    r = client.post(
        f"{LEAVES}/{leave_id}/decision",
        headers=mentor.headers,
        json={"decision": "APPROVE", "note": note},
    )
    assert r.status_code == 200, r.text
    mine = client.get(f"{LEAVES}/mine", headers=student.headers).json()
    assert [row["director_note"] for row in mine if row["id"] == leave_id] == [note]


@requires_db
def test_a_student_with_no_mentor_goes_to_the_office(client, people):
    student, mentor, office = people["student"], people["mentor"], people["office"]
    _unseat(student.user_id)

    route = client.get(f"{LEAVES}/mine/approver", headers=student.headers)
    assert route.status_code == 200, route.text
    assert route.json()["routed_to"] == "OFFICE"
    assert route.json()["mentor_name"] is None

    leave_id = _submit(client, student.headers, leave_kind="OOD")["id"]
    assert leave_id in _ids(client.get(f"{LEAVES}/pending", headers=office.headers))
    # A mentor who mentors somebody else cannot reach it.
    other = people["other"]
    assert leave_id not in _ids(client.get(f"{LEAVES}/mentees", headers=other.headers))
    assert client.post(
        f"{LEAVES}/{leave_id}/decision", headers=other.headers, json=APPROVE
    ).status_code == 404
    # The former mentor now has no mentees, so the queue is not theirs at all.
    assert client.get(f"{LEAVES}/mentees", headers=mentor.headers).status_code == 403

    done = client.post(f"{LEAVES}/{leave_id}/decision", headers=office.headers, json=APPROVE)
    assert done.status_code == 200, done.text
    assert done.json()["first_signed_as"] == "MAIN_ADMIN"


@requires_db
def test_the_route_names_the_mentor_and_follows_a_reassignment(client, people):
    student, mentor, other = people["student"], people["mentor"], people["other"]
    route = client.get(f"{LEAVES}/mine/approver", headers=student.headers).json()
    assert route["routed_to"] == "MENTOR"
    assert route["mentor_name"] == "Voice Test sl-men"

    leave_id = _submit(client, student.headers)["id"]
    _seat(student.user_id, other.user_id)
    assert leave_id in _ids(client.get(f"{LEAVES}/mentees", headers=other.headers))
    # The former mentor has no mentee left, so they are refused at the door.
    assert client.post(
        f"{LEAVES}/{leave_id}/decision", headers=mentor.headers, json=APPROVE
    ).status_code == 403
    done = client.post(f"{LEAVES}/{leave_id}/decision", headers=other.headers, json=APPROVE)
    assert done.status_code == 200 and done.json()["first_signed_as"] == "MENTOR"


@requires_db
def test_a_disabled_mentor_hands_the_request_to_the_office(client, people):
    student, mentor, office = people["student"], people["mentor"], people["office"]
    leave_id = _submit(client, student.headers)["id"]
    with SessionLocal() as db:
        from datetime import datetime, timezone

        db.get(User, mentor.user_id).disabled_at = datetime.now(timezone.utc)
        db.commit()
    assert leave_id in _ids(client.get(f"{LEAVES}/pending", headers=office.headers))


@requires_db
def test_the_student_form_takes_three_types_and_no_overlap(client, people):
    headers = people["student"].headers
    for kind in ("PERMISSION", "LOP", None):
        r = client.post(
            LEAVES,
            headers=headers,
            json={"from_date": "2026-12-01", "to_date": "2026-12-01", "reason": "x", "leave_kind": kind},
        )
        assert r.status_code == 422, (kind, r.text)
        assert "Medical, Casual or On official duty" in r.text

    _submit(client, headers, from_date="2026-12-01", to_date="2026-12-03")
    clash = client.post(
        LEAVES,
        headers=headers,
        json={"from_date": "2026-12-03", "to_date": "2026-12-04", "reason": "x", "leave_kind": "CASUAL"},
    )
    assert clash.status_code == 422 and "overlaps" in clash.text


@requires_db
def test_faculty_may_still_apply_without_the_student_rules(client, make_user):
    """The student rules are the student's: a faculty applicant still submits
    with no leave type, as the paper form allows."""
    faculty = make_user("sl-fac", Role.MENTOR)
    r = client.post(
        LEAVES,
        headers=faculty.headers,
        json={"from_date": "2026-12-20", "to_date": "2026-12-20", "reason": "Personal work."},
    )
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        db.execute(delete(LeaveRequest).where(LeaveRequest.id == r.json()["id"]))
        db.commit()


@requires_db
def test_the_student_withdraws_a_pending_request(client, people):
    student, mentor = people["student"], people["mentor"]
    leave_id = _submit(client, student.headers)["id"]
    r = client.post(f"{LEAVES}/{leave_id}/cancel", headers=student.headers)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert leave_id not in _ids(client.get(f"{LEAVES}/mentees", headers=mentor.headers))


@requires_db
def test_the_supporting_document_reaches_the_mentor_and_nobody_else(client, people):
    student, mentor, other, office = (
        people["student"], people["mentor"], people["other"], people["office"]
    )
    leave_id = _submit(client, student.headers)["id"]
    up = client.post(
        f"{LEAVES}/{leave_id}/attachments",
        headers=student.headers,
        files={"file": ("certificate.pdf", APPLICATION_CV, "application/pdf")},
    )
    assert up.status_code == 201, up.text
    attachment_id = up.json()["id"]
    try:
        row = next(
            r for r in client.get(f"{LEAVES}/mentees", headers=mentor.headers).json()
            if r["id"] == leave_id
        )
        assert row["attachments"] == [{"id": attachment_id, "original_name": "certificate.pdf"}]
        assert row["requester_usn"] is None  # make_user's student has no USN
        url = f"{LEAVES}/{leave_id}/attachments/{attachment_id}/file"
        assert client.get(url, headers=mentor.headers).status_code == 200
        assert client.get(url, headers=other.headers).status_code == 404
        assert client.get(url, headers=office.headers).status_code == 404
    finally:
        client.delete(f"{LEAVES}/{leave_id}/attachments/{attachment_id}", headers=student.headers)


@requires_db
def test_the_mentee_queue_needs_a_mentee(client, make_user, people):
    lone = make_user("sl-lone", Role.MENTOR)
    assert client.get(f"{LEAVES}/mentees", headers=lone.headers).status_code == 403
    assert client.get(f"{LEAVES}/mentees", headers=people["office"].headers).status_code == 403
    assert client.get(f"{LEAVES}/mentees", headers=people["student"].headers).status_code == 403
    # And without a mentee or a grant, the decision door is shut as before.
    assert client.post(
        f"{LEAVES}/no-such-leave/decision", headers=lone.headers, json=APPROVE
    ).status_code == 403
