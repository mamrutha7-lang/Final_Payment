import {
  STUDENT_LEAVE_KINDS,
  initials,
  isPending,
  leaveDateRange,
  leaveKindLabel,
  leaveStatusLabel,
  leaveStatusTone,
  leaveTotalDays,
} from './leave';

describe('leave helpers', () => {
  it('offers students exactly the three types the server accepts, in order', () => {
    expect([...STUDENT_LEAVE_KINDS]).toEqual(['MEDICAL', 'CASUAL', 'OOD']);
    expect(STUDENT_LEAVE_KINDS.map(leaveKindLabel)).toEqual(['Medical', 'Casual', 'On official duty']);
    expect(leaveKindLabel(null)).toBe('Leave');
  });

  it('counts both ends of the span, across a month and a year', () => {
    expect(leaveTotalDays('2026-11-04', '2026-11-06')).toBe(3);
    expect(leaveTotalDays('2026-11-06', '2026-11-06')).toBe(1);
    expect(leaveTotalDays('2026-11-30', '2026-12-02')).toBe(3);
    expect(leaveTotalDays('2026-12-31', '2027-01-01')).toBe(2);
  });

  it('gives no count for a missing or backwards span', () => {
    expect(leaveTotalDays('', '2026-11-06')).toBe(0);
    expect(leaveTotalDays('2026-11-06', '2026-11-04')).toBe(0);
  });

  it('writes the dates the way the design does', () => {
    expect(leaveDateRange('2026-11-04', '2026-11-06')).toBe('04–06 Nov 2026');
    expect(leaveDateRange('2026-11-06', '2026-11-06')).toBe('06 Nov 2026');
    expect(leaveDateRange('2026-11-30', '2026-12-02')).toBe('30 Nov – 02 Dec 2026');
    expect(leaveDateRange('2026-12-28', '2027-01-02')).toBe('28 Dec 2026 – 02 Jan 2027');
  });

  it('names every status in words and pairs it with a tone', () => {
    expect(leaveStatusLabel('SUBMITTED')).toBe('Pending');
    expect(leaveStatusLabel('FIRST_APPROVED')).toBe('Pending');
    expect(leaveStatusLabel('CANCELLED')).toBe('Withdrawn');
    expect(leaveStatusTone('APPROVED')).toBe('good');
    expect(leaveStatusTone('SUBMITTED')).toBe('warn');
    expect(leaveStatusTone('REJECTED')).toBe('risk');
    expect(leaveStatusTone('CANCELLED')).toBe('neutral');
    expect(isPending('FIRST_APPROVED')).toBe(true);
    expect(isPending('APPROVED')).toBe(false);
  });

  it('makes two-letter initials', () => {
    expect(initials('Priya S')).toBe('PS');
    expect(initials('Asha Rao')).toBe('AR');
    expect(initials('Rakshita')).toBe('RA');
  });
});
