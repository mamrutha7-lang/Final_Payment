/**
 * Student courses — a PROGRESS PLAN over GET /student/courses.
 *
 * Each enrolment renders as a warm v2 card that answers "where am I, and what do
 * I do next?": a % progress meter, the single NEXT TASK, the stage it belongs to,
 * an estimate of what's left, a Continue CTA and an "Unlocks" line. All shaping —
 * the lecture ratio, the stage enum, progress_pct, next_task and unlocks — is
 * computed server-side (rule-based, no LLM); this component only maps the enum
 * labels onto tones and lays the fields out.
 */

import { Component, computed, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { environment } from '../../../../environments/environment';

interface Course {
  code: string;
  name: string;
  stage: string;
  dimension: string;
  semester: number;
  status: string;
  teaching_hours_attended: number;
  self_learning_hours_logged: number;
  lectures_attended: number;
  lectures_total: number;
  lecture_percent: number;
  // Progress-plan fields from the enriched endpoint.
  progress_pct: number;
  next_task: string;
  unlocks: string;
}

type LoadState = 'loading' | 'ready' | 'error';

interface Chip {
  cls: string;
  icon: string;
  label: string;
}

@Component({
  selector: 'app-student-courses',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './courses.component.html',
  styleUrl: './courses.component.scss',
})
export class CoursesComponent {
  readonly courses = signal<Course[]>([]);
  readonly state = signal<LoadState>('loading');

  readonly completedCount = computed(
    () => this.courses().filter((c) => c.status === 'COMPLETED').length,
  );
  readonly inProgressCount = computed(
    () => this.courses().filter((c) => c.status === 'IN_PROGRESS').length,
  );

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const res = await fetch(`${environment.apiBase}/student/courses`, { credentials: 'include' });
      if (!res.ok) {
        this.state.set('error');
        return;
      }
      this.courses.set((await res.json()) as Course[]);
      this.state.set('ready');
    } catch {
      this.state.set('error');
    }
  }

  /// REBOOT → Reboot, EXCEL_ADVANCED → Excel Advanced.
  stageLabel(stage: string): string {
    return stage
      .toLowerCase()
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }

  /// Map the ProgressStatus enum onto the global .chip tones + a Material Symbol.
  statusChip(status: string): Chip {
    switch (status) {
      case 'COMPLETED':
        return { cls: 'good', icon: 'check_circle', label: 'Completed' };
      case 'IN_PROGRESS':
        return { cls: 'warn', icon: 'pending', label: 'In progress' };
      case 'OVERDUE':
        return { cls: 'risk', icon: 'warning', label: 'Overdue' };
      default:
        return { cls: 'neutral', icon: 'schedule', label: 'Not started' };
    }
  }

  /// Lectures still to attend — the honest "time remaining" a course can offer.
  lecturesLeft(c: Course): number {
    return Math.max(0, c.lectures_total - c.lectures_attended);
  }
}
