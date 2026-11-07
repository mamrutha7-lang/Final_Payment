/**
 * My leave — the student's own leave requests and where each one stands.
 *
 * Reads two endpoints and writes one: `/leaves/mine/approver` (the header:
 * who the student is and who decides their leave), `/leaves/mine` (the list),
 * and `/leaves/{id}/cancel` to withdraw a request that is still pending.
 * Applying is a separate screen (request-leave.component.ts).
 */

import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  LeaveRoute,
  LeaveRow,
  isPending,
  leaveApi,
  leaveDateRange,
  leaveKindLabel,
  leaveStatusLabel,
  leaveStatusTone,
} from '../../../core/leave';

@Component({
  selector: 'app-my-leave',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './my-leave.component.html',
  styleUrl: './leave.scss',
})
export class MyLeaveComponent {
  private readonly route = inject(ActivatedRoute);

  readonly kindLabel = leaveKindLabel;
  readonly statusLabel = leaveStatusLabel;
  readonly statusTone = leaveStatusTone;
  readonly dateRange = leaveDateRange;
  readonly isPending = isPending;

  readonly me = signal<LeaveRoute | null>(null);
  readonly rows = signal<LeaveRow[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  /** The row whose Withdraw is waiting for its confirmation. */
  readonly confirming = signal<string | null>(null);
  readonly busy = signal(false);

  constructor() {
    // Set by Request leave after a send, so the confirmation is read here,
    // beside the new row, rather than on a screen the student has left.
    const sent = this.route.snapshot.queryParamMap.get('sent');
    if (sent === 'MENTOR') this.notice.set('Your request was sent to your mentor.');
    if (sent === 'OFFICE') this.notice.set('Your request was sent to the placement office.');
    void this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const [me, rows] = await Promise.all([leaveApi.myRoute(), leaveApi.mine()]);
      this.me.set(me);
      this.rows.set(rows);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loading.set(false);
    }
  }

  askWithdraw(row: LeaveRow): void {
    this.confirming.set(row.id);
    this.notice.set(null);
  }

  keep(): void {
    this.confirming.set(null);
  }

  async withdraw(row: LeaveRow): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await leaveApi.withdraw(row.id);
      this.notice.set(`Your ${leaveKindLabel(row.leave_kind).toLowerCase()} leave request was withdrawn.`);
      this.confirming.set(null);
      await this.load();
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.busy.set(false);
    }
  }
}
