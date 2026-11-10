import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import type { ReviewMetric, WeeklyReview } from "../types";

const day = (iso: string, withMonth = true) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, withMonth ? { day: "numeric", month: "short" } : { day: "numeric" });

function range(start: string, end: string): string {
  const sameMonth = start.slice(0, 7) === end.slice(0, 7);
  return `${sameMonth ? day(start, false) : day(start)}–${day(end)}`;
}

function title(review: WeeklyReview, thisWeek: string | null): string {
  if (review.week.is_current) return "This week";
  if (thisWeek && review.next_week === thisWeek) return "Last week";
  return `Week of ${day(review.week.start)}`;
}

function comparison(metric: ReviewMetric, review: WeeklyReview): string {
  const by = review.week.compared_through ? ` by ${review.week.compared_through}` : "";
  const parts = [`Last week${by}: ${metric.last_week.display ?? "—"}`];
  if (metric.average) parts.push(`${review.weeks_in_average}-week avg: ${metric.average.display ?? "—"}`);
  return parts.join(" · ");
}

function changeLabel(metric: ReviewMetric): string {
  if (!metric.change) return "Same as last week";
  const amount = metric.change.slice(1);
  return `${amount} ${metric.direction === "up" ? "more" : "less"} than last week`;
}

/** The week in numbers from your records, against last week and your usual week. */
export function WeekReview() {
  const [week, setWeek] = useState<string | null>(null);
  const [review, setReview] = useState<WeeklyReview | null>(null);
  const [thisWeek, setThisWeek] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    api<WeeklyReview>(`/v1/review/weekly${week ? `?week=${week}` : ""}`)
      .then((data) => {
        setReview(data);
        if (data.week.is_current) setThisWeek(data.week.start);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [week]);

  useEffect(load, [load]);

  if (failed) {
    return (
      <p className="error">
        Can't load your week right now.{" "}
        <button className="link" onClick={load}>
          Try again
        </button>
      </p>
    );
  }
  if (!review) return null;

  const heading = title(review, thisWeek);
  return (
    <section aria-labelledby="week-title" className="week-review">
      <div className="week-nav">
        <button className="chip" aria-label="Previous week" onClick={() => setWeek(review.previous_week)}>
          ‹
        </button>
        <h2 id="week-title">
          {heading} · {range(review.week.start, review.week.end)}
        </h2>
        <button
          className="chip"
          aria-label="Next week"
          disabled={!review.next_week}
          onClick={() => review.next_week && setWeek(review.next_week === thisWeek ? null : review.next_week)}
        >
          ›
        </button>
      </div>

      {review.observations.length > 0 && (
        <div className="card question">
          <h3 className="card-title">What stands out</h3>
          <ul className="observations">
            {review.observations.map((item, index) => (
              <li key={index}>{item.text}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="card" style={{ marginTop: review.observations.length ? 12 : 0 }}>
        {review.metrics.map((metric) => (
          <div className="row" key={metric.key}>
            <span className="label">
              {metric.label}
              {metric.currency && review.metrics.filter((m) => m.kind === "money").length > 1 ? ` (${metric.currency})` : ""}
              <span className="sub wrap">{comparison(metric, review)}</span>
              {metric.note && <span className="sub wrap">{metric.note}</span>}
            </span>
            <span className="value-stack">
              <span className="value">{metric.this_week.display ?? "—"}</span>
              <span className="change">
                <span aria-hidden="true">{metric.change ?? "="}</span>
                <span className="sr-only">{changeLabel(metric)}</span>
              </span>
            </span>
          </div>
        ))}
      </div>

      {review.habits.length > 0 && (
        <div className="card" style={{ marginTop: 12 }}>
          {review.habits.map((habit) => (
            <div className="row" key={habit.habit_id}>
              <span className="label">{habit.name}</span>
              <span className="value">{habit.display}</span>
            </div>
          ))}
        </div>
      )}

      <p className="faint" style={{ margin: "10px 4px 0" }}>
        {review.week.compared_through
          ? `Earlier weeks are counted up to ${review.week.compared_through}, so the comparison is fair. `
          : ""}
        {review.weeks_in_average === 0
          ? "Averages start once you have a week of history."
          : `The average covers the ${review.weeks_in_average === 1 ? "week" : `${review.weeks_in_average} weeks`} before this one.`}{" "}
        Every number comes from your records.
      </p>
    </section>
  );
}
