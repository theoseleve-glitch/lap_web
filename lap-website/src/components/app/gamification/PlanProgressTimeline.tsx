'use client';

import type { DrillExecution } from './types';

interface WeekDrill {
  name: string;
  description?: string;
}

interface WeekData {
  week_number: number;
  drills: WeekDrill[];
}

interface PlanProgressTimelineProps {
  weeks: WeekData[];
  executions: DrillExecution[];
  className?: string;
}

function findExecution(
  executions: DrillExecution[],
  weekNumber: number,
  drillIndex: number,
): DrillExecution | undefined {
  return executions.find(
    (ex) => ex.week_number === weekNumber && ex.drill_index === drillIndex,
  );
}

function getWeekCompletion(
  week: WeekData,
  executions: DrillExecution[],
): { completed: number; total: number; percent: number } {
  const total = week.drills.length;
  if (total === 0) return { completed: 0, total: 0, percent: 0 };

  let completed = 0;
  for (let i = 0; i < total; i++) {
    const ex = findExecution(executions, week.week_number, i);
    if (ex?.status === 'completed') completed++;
  }

  return {
    completed,
    total,
    percent: Math.round((completed / total) * 100),
  };
}

function isWeekComplete(week: WeekData, executions: DrillExecution[]): boolean {
  const { completed, total } = getWeekCompletion(week, executions);
  return total > 0 && completed === total;
}

/** Status icon for each drill */
function DrillStatusIcon({ execution }: { execution: DrillExecution | undefined }) {
  if (!execution) {
    // No execution recorded
    return (
      <span
        className="inline-block w-5 h-5 rounded-full border-2 flex-shrink-0"
        style={{ borderColor: '#94a3b8' }}
      />
    );
  }

  if (execution.status === 'completed') {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full flex-shrink-0"
        style={{ backgroundColor: '#a3e635' }}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M2.5 6L5 8.5L9.5 3.5"
            stroke="#1a1a2e"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }

  if (execution.status === 'attempted') {
    return (
      <span
        className="inline-flex items-center justify-center w-5 h-5 rounded-full flex-shrink-0"
        style={{ backgroundColor: 'rgba(245, 158, 11, 0.2)', border: '1.5px solid #f59e0b' }}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle cx="6" cy="6" r="4.5" stroke="#f59e0b" strokeWidth="1.5" />
          <path d="M6 3.5V6L7.5 7.5" stroke="#f59e0b" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </span>
    );
  }

  // skipped
  return (
    <span
      className="inline-block w-5 h-5 rounded-full flex-shrink-0"
      style={{ backgroundColor: 'rgba(148, 163, 184, 0.3)', border: '1.5px solid #94a3b8' }}
    />
  );
}

export default function PlanProgressTimeline({
  weeks,
  executions,
  className = '',
}: PlanProgressTimelineProps) {
  return (
    <div className={`relative ${className}`}>
      {weeks.map((week, weekIdx) => {
        const completion = getWeekCompletion(week, executions);
        const weekComplete = isWeekComplete(week, executions);
        const isLast = weekIdx === weeks.length - 1;

        return (
          <div key={week.week_number} className="relative flex gap-4">
            {/* Timeline column */}
            <div className="flex flex-col items-center flex-shrink-0" style={{ width: '28px' }}>
              {/* Week node */}
              <div
                className="w-7 h-7 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                style={{
                  borderColor: weekComplete ? '#a3e635' : '#94a3b8',
                  backgroundColor: weekComplete
                    ? 'rgba(163, 230, 53, 0.2)'
                    : 'rgba(148, 163, 184, 0.1)',
                }}
              >
                <span
                  className="font-telemetry text-xs font-bold"
                  style={{ color: weekComplete ? '#a3e635' : '#94a3b8' }}
                >
                  {week.week_number}
                </span>
              </div>

              {/* Connecting line */}
              {!isLast && (
                <div
                  className="flex-1 w-0.5 min-h-[24px]"
                  style={{
                    backgroundColor: weekComplete ? '#a3e635' : '#94a3b8',
                    opacity: weekComplete ? 0.6 : 0.3,
                  }}
                />
              )}
            </div>

            {/* Content column */}
            <div className="flex-1 pb-6">
              {/* Week header */}
              <div className="flex items-baseline gap-2 mb-2">
                <h3 className="font-monument text-sm font-semibold text-chalk">
                  Week {week.week_number}
                </h3>
                <span
                  className="font-telemetry text-xs"
                  style={{
                    color: completion.percent === 100 ? '#a3e635' : '#94a3b8',
                  }}
                >
                  {completion.percent}%
                </span>
              </div>

              {/* Drill list */}
              <ul className="space-y-2">
                {week.drills.map((drill, drillIdx) => {
                  const ex = findExecution(executions, week.week_number, drillIdx);
                  return (
                    <li key={drillIdx} className="flex items-start gap-2">
                      <DrillStatusIcon execution={ex} />
                      <div className="min-w-0">
                        <p
                          className="text-sm font-body"
                          style={{
                            color: ex?.status === 'completed' ? '#e2e8f0' : '#94a3b8',
                          }}
                        >
                          {drill.name}
                        </p>
                        {drill.description && (
                          <p className="text-xs text-steel mt-0.5 line-clamp-2">
                            {drill.description}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        );
      })}
    </div>
  );
}
