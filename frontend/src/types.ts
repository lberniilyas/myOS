export type EntityRef = { id: string; name: string };

export type EventSummary = {
  id: string;
  event_type: string;
  title: string;
  category: string | null;
  occurred_on: string;
  occurred_at: string | null;
  ended_at: string | null;
  local_time: string | null;
  day_period: string | null;
  time_precision: string;
  duration_seconds: number | null;
  duration_precision: string;
  duration_display: string | null;
  amount: string | null;
  currency: string | null;
  amount_precision: string | null;
  amount_display: string | null;
  projects: EntityRef[];
  source_type: string;
  capture_id: string | null;
  created_at: string;
};

export type EventDetail = EventSummary & {
  description: string | null;
  structured_data: Record<string, unknown>;
  area: EntityRef | null;
  goals: EntityRef[];
  knowledge: { id: string; title: string; understanding_state: string }[];
  tasks: EntityRef[];
  habits: { id: string; name: string; outcome: string }[];
  provenance: {
    source_type: string;
    created_by: string;
    input_type: string | null;
    captured_at: string | null;
    evidence: string | null;
    confidence_label: string | null;
    model_name: string | null;
  };
  corrected_at: string | null;
  deleted_at: string | null;
  revision_count: number;
  related_event_count: number;
};

export type ClarificationOption = { id: string; label: string; value: unknown };

export type Clarification = {
  id: string;
  kind: string;
  question: string;
  options: ClarificationOption[];
  answer_type: "choice" | "amount";
  event_id: string | null;
  capture_id: string;
  status: string;
};

export type CaptureResult = {
  capture: { id: string; status: string; input_type: string; captured_at: string };
  message: string;
  events_created: EventSummary[];
  events_updated: { event: EventSummary; changes: string[] }[];
  events_deleted: { id: string; title: string }[];
  tasks_created: { id: string; title: string; due_date: string | null }[];
  clarifications: Clarification[];
  warnings: string[];
  answer: { text: string } | null;
  error: { code: string; message: string; retryable: boolean } | null;
};

export type TimeRow = {
  key: string;
  label: string;
  seconds: number;
  display: string | null;
  events: number;
  events_without_duration: number;
};

export type MoneyRow = { currency: string | null; amount: string; display: string | null; events: number };

export type DailySummary = {
  date: string;
  events_count: number;
  time: TimeRow[];
  projects: TimeRow[];
  devices: { device: string; seconds: number; display: string | null }[];
  spending: MoneyRow[];
  income: MoneyRow[];
  knowledge: { id: string; title: string; understanding_state: string }[];
  tasks_completed: { id: string; title: string }[];
  habits: { habit_id: string; name: string; status: string }[];
  states: { title: string; dimension?: string; value?: string }[];
  recent_events: EventSummary[];
};

export type User = {
  id: string;
  email: string;
  name: string | null;
  timezone: string;
  locale: string;
  default_currency: string | null;
  week_start: number;
};

export type Project = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  aliases: string[];
  goals: EntityRef[];
};

export type Habit = { id: string; name: string; frequency: string; target_count: number | null; status: string };
export type Goal = { id: string; title: string; status: string; projects: EntityRef[] };
export type Knowledge = {
  id: string;
  title: string;
  understanding_state: string;
  aliases: string[];
  evidence_count: number;
  last_seen_on: string | null;
};
export type Task = { id: string; title: string; status: string; due_date: string | null; project: EntityRef | null };
