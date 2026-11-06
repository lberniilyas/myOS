import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { EventRow } from "../components";
import { dayHeading, localToday, whenLabel } from "../format";
import type { EventSummary } from "../types";

type Page = { items: EventSummary[]; next_cursor: string | null };

export function Timeline({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<EventSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const latest = useRef(0);

  async function load(reset: boolean, search = query) {
    const request = ++latest.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: "40" });
    if (search.trim()) params.set("q", search.trim());
    if (!reset && cursor) params.set("cursor", cursor);
    try {
      const page = await api<Page>(`/v1/timeline?${params}`);
      if (request !== latest.current) return; // a newer search already answered
      setItems((current) => (reset ? page.items : [...current, ...page.items]));
      setCursor(page.next_cursor);
      setFailed(false);
    } catch {
      if (request === latest.current) setFailed(true);
    } finally {
      if (request === latest.current) setLoading(false);
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => load(true, query), query ? 300 : 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, refreshKey]);

  const today = localToday();
  const days: [string, EventSummary[]][] = [];
  for (const event of items) {
    const last = days[days.length - 1];
    if (last && last[0] === event.occurred_on) last[1].push(event);
    else days.push([event.occurred_on, [event]]);
  }

  return (
    <>
      <h1>Timeline</h1>
      <input className="field" type="search" placeholder="Search your history" value={query} onChange={(e) => setQuery(e.target.value)} />
      {days.map(([day, events]) => (
        <div key={day}>
          <h2>{dayHeading(day, today)}</h2>
          <div className="card">
            {events.map((event) => (
              <EventRow key={event.id} event={event} showTime={events.some((e) => whenLabel(e))} />
            ))}
          </div>
        </div>
      ))}
      {failed && (
        <div className="card empty">
          Can't reach your system right now.{" "}
          <button className="link" onClick={() => load(items.length === 0)}>
            Try again
          </button>
        </div>
      )}
      {!loading && !failed && items.length === 0 && (
        <div className="empty">{query ? "Nothing matches that." : "Your timeline fills up as you tell your system what happened."}</div>
      )}
      {cursor && (
        <p style={{ textAlign: "center", marginTop: 18 }}>
          <button className="link" onClick={() => load(false)} disabled={loading}>
            {loading ? "Loading…" : "Show earlier"}
          </button>
        </p>
      )}
    </>
  );
}
