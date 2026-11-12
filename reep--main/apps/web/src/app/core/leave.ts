/**
 * Student leave (2026-11-05), shared by the student's My leave and Request
 * leave screens (features/student/leave) and the mentor's Student leave
 * requests screen (features/mentor/student-leave).
 *
 * Who decides a request is the server's rule (apps/api-py/app/student_leave.py):
 * a student's mentor, or the placement office when the student has none. This
 * file only names things, formats them and calls the endpoints; it decides
 * nothing.
 */

import { environment } from '../../environments/environment';
import { apiJson, detailOf } from './api-json';
import { UPLOAD_DROPPED_MESSAGE } from './picked-file';

/** The three types a student may apply for, in the order the form lists them.
 *  The server holds the same list (`STUDENT_LEAVE_KINDS`) and refuses others. */
export const STUDENT_LEAVE_KINDS = ['MEDICAL', 'CASUAL', 'OOD'] as const;
export type StudentLeaveKind = (typeof STUDENT_LEAVE_KINDS)[number];

/** The types that cannot be sent without a supporting document. The server
 *  holds the same list (`DOCUMENT_REQUIRED_KINDS`) and refuses a request of
 *  these types that arrives without one. */
export const DOCUMENT_REQUIRED_KINDS: readonly StudentLeaveKind[] = ['MEDICAL'];

export function documentRequired(kind: string | null | undefined): boolean {
  return !!kind && (DOCUMENT_REQUIRED_KINDS as readonly string[]).includes(kind);
}

const KIND_LABELS: Record<string, string> = {
  MEDICAL: 'Medical',
  CASUAL: 'Casual',
  OOD: 'On official duty',
  PERMISSION: 'Permission',
  RH: 'Restricted holiday',
  LOP: 'Loss of pay',
};

export function leaveKindLabel(kind: string | null | undefined): string {
  return (kind && KIND_LABELS[kind]) || 'Leave';
}

/** What a student and a mentor read for each status. FIRST_APPROVED is a row
 *  from the retired two-signature chain: still waiting, so "Pending". */
const STATUS_LABELS: Record<string, string> = {
  SUBMITTED: 'Pending',
  FIRST_APPROVED: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  CANCELLED: 'Withdrawn',
  REVOKED: 'Revoked',
};

export function leaveStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/** The chip colour, always drawn beside the word (never colour alone). */
export function leaveStatusTone(status: string): 'good' | 'warn' | 'risk' | 'neutral' {
  if (status === 'APPROVED') return 'good';
  if (status === 'SUBMITTED' || status === 'FIRST_APPROVED') return 'warn';
  if (status === 'REJECTED' || status === 'REVOKED') return 'risk';
  return 'neutral';
}

export function isPending(status: string): boolean {
  return status === 'SUBMITTED' || status === 'FIRST_APPROVED';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return [y, m, d];
}

/** "04–06 Nov 2026", "06 Nov 2026", "30 Nov – 02 Dec 2026", "28 Dec 2026 – 02 Jan 2027".
 *  Read from the ISO date's own digits, never through `Date`, so a time zone
 *  cannot move a day. */
export function leaveDateRange(from: string, to: string): string {
  const [fy, fm, fd] = parts(from);
  const [ty, tm, td] = parts(to);
  const day = (n: number) => String(n).padStart(2, '0');
  if (from === to) return `${day(fd)} ${MONTHS[fm - 1]} ${fy}`;
  if (fy === ty && fm === tm) return `${day(fd)}–${day(td)} ${MONTHS[fm - 1]} ${fy}`;
  if (fy === ty) return `${day(fd)} ${MONTHS[fm - 1]} – ${day(td)} ${MONTHS[tm - 1]} ${fy}`;
  return `${day(fd)} ${MONTHS[fm - 1]} ${fy} – ${day(td)} ${MONTHS[tm - 1]} ${ty}`;
}

/** Calendar days from `from` to `to`, both included; 0 when either is missing
 *  or the span runs backwards (the server refuses that, and so does the form). */
export function leaveTotalDays(from: string, to: string): number {
  if (!from || !to) return 0;
  const [fy, fm, fd] = parts(from);
  const [ty, tm, td] = parts(to);
  const days = (Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86_400_000 + 1;
  return days > 0 ? days : 0;
}

/** Two letters for the avatar: "Priya S" -> "PS". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] ?? '?').slice(0, 2);
  return letters.toUpperCase();
}

// --------------------------------------------------------------- the API --

/** One request, as `GET /leaves/mine` and the decision endpoint answer it.
 *  Only the fields these screens read. */
export interface LeaveRow {
  id: string;
  from_date: string;
  to_date: string;
  reason: string;
  status: string;
  leave_kind: string | null;
  requester_name: string;
  director_name: string | null;
  director_note: string | null;
}

export interface LeaveFile {
  id: string;
  original_name: string;
}

/** A mentee's request, as the mentor's queue answers it. */
export interface MenteeLeaveRow extends LeaveRow {
  requester_usn: string | null;
  attachments: LeaveFile[];
}

/** Who decides my leave, and the header of My leave. */
export interface LeaveRoute {
  name: string;
  usn: string | null;
  course: string | null;
  mentor_name: string | null;
  routed_to: 'MENTOR' | 'OFFICE';
}

export interface NewLeave {
  leave_kind: StudentLeaveKind;
  from_date: string;
  to_date: string;
  reason: string;
}

export type MenteeQueueTab = 'PENDING' | 'APPROVED' | 'REJECTED';

export const leaveApi = {
  myRoute: () => apiJson<LeaveRoute>('/leaves/mine/approver', {}, 'Could not load your details'),
  mine: () => apiJson<LeaveRow[]>('/leaves/mine', {}, 'Could not load your leave'),
  withdraw: (id: string) =>
    apiJson<LeaveRow>(`/leaves/${id}/cancel`, { method: 'POST' }, 'Could not withdraw the request'),
  menteeQueue: (tab: MenteeQueueTab) =>
    apiJson<MenteeLeaveRow[]>(`/leaves/mentees?status=${tab}`, {}, 'Could not load leave requests'),
  /** `note` is required to reject (the server refuses a blank one) and
   *  optional to approve. The applicant reads it on My leave. */
  decide: (id: string, decision: 'APPROVE' | 'REJECT', note: string | null) =>
    apiJson<LeaveRow>(
      `/leaves/${id}/decision`,
      { method: 'POST', body: JSON.stringify({ decision, note }) },
      'Could not record the decision',
    ),
};

/** Send a student's request and its supporting document together, in one
 *  request (`POST /leaves/student`), so the server can refuse a medical leave
 *  that has no document and never saves a request whose file failed. `file`
 *  may be null for the types where the document is optional. Throws an Error
 *  whose message is the screen's sentence. */
export async function submitStudentLeave(body: NewLeave, file: File | null): Promise<LeaveRow> {
  const form = new FormData();
  form.append('leave_kind', body.leave_kind);
  form.append('from_date', body.from_date);
  form.append('to_date', body.to_date);
  form.append('reason', body.reason);
  if (file) form.append('file', file, file.name);
  let res: Response;
  try {
    res = await fetch(`${environment.apiBase}/leaves/student`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    });
  } catch {
    throw new Error(UPLOAD_DROPPED_MESSAGE);
  }
  if (!res.ok) throw new Error(await detailOf(res, 'Could not send your request'));
  return (await res.json()) as LeaveRow;
}

/** Attach a supporting document to a request that already exists. Throws an
 *  Error whose message is the screen's sentence. */
export async function attachLeaveDocument(leaveId: string, file: File): Promise<void> {
  const form = new FormData();
  form.append('file', file, file.name);
  let res: Response;
  try {
    res = await fetch(`${environment.apiBase}/leaves/${leaveId}/attachments`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    });
  } catch {
    throw new Error(UPLOAD_DROPPED_MESSAGE);
  }
  if (!res.ok) throw new Error(await detailOf(res, 'The document did not upload'));
}

/** The download URL of one supporting document, for an `<a href download>`. */
export function leaveDocumentUrl(leaveId: string, fileId: string): string {
  return `${environment.apiBase}/leaves/${leaveId}/attachments/${fileId}/file`;
}
