export const TYPE_LABELS: Record<string, string> = {
  STUDY: "Study",
  WORK: "Work",
  PROJECT_WORK: "Project",
  KNOWLEDGE: "Knowledge",
  TASK_ACTIVITY: "Task",
  HABIT: "Habit",
  EXERCISE: "Exercise",
  EXPENSE: "Spending",
  INCOME: "Income",
  DEVICE_USAGE: "Device",
  SLEEP: "Sleep",
  JOURNAL: "Journal",
  STATE: "How you felt",
  MILESTONE: "Milestone",
  GOAL_PROGRESS: "Goal",
  OTHER: "Other",
};

export const TYPE_MARKS: Record<string, string> = {
  STUDY: "📚",
  WORK: "💼",
  PROJECT_WORK: "💻",
  KNOWLEDGE: "🧠",
  TASK_ACTIVITY: "✓",
  HABIT: "↻",
  EXERCISE: "🏃",
  EXPENSE: "💳",
  INCOME: "💰",
  DEVICE_USAGE: "📱",
  SLEEP: "🌙",
  JOURNAL: "✎",
  STATE: "◐",
  MILESTONE: "★",
  GOAL_PROGRESS: "◎",
  OTHER: "•",
};

const PERIODS: Record<string, string> = { MORNING: "Morning", AFTERNOON: "Afternoon", EVENING: "Evening", NIGHT: "Night" };

export function whenLabel(event: { local_time: string | null; day_period: string | null; time_precision: string }): string {
  if (event.local_time) return event.time_precision === "APPROXIMATE" ? `~${event.local_time}` : event.local_time;
  if (event.day_period) return PERIODS[event.day_period] ?? "";
  return "";
}

export function dayHeading(isoDate: string, today: string): string {
  if (isoDate === today) return "Today";
  const date = new Date(`${isoDate}T12:00:00`);
  const yesterday = new Date(`${today}T12:00:00`);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

export function localToday(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function eventValue(event: { duration_display: string | null; amount_display: string | null }): string {
  return event.amount_display ?? event.duration_display ?? "";
}
