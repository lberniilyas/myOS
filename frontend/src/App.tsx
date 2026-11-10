import { useCallback, useEffect, useState } from "react";

import { api, flushQueue, isSignedIn, pendingCaptures } from "./api";
import { CaptureSheet, TabBar, Toast } from "./components";
import { Deleted } from "./screens/Deleted";
import { EventDetail } from "./screens/EventDetail";
import { Goal } from "./screens/Goal";
import { Habit } from "./screens/Habit";
import { Home } from "./screens/Home";
import { Insights } from "./screens/Insights";
import { Knowledge } from "./screens/Knowledge";
import { Login } from "./screens/Login";
import { Me } from "./screens/Me";
import { Project } from "./screens/Project";
import { Shortcuts } from "./screens/Shortcuts";
import { Tasks } from "./screens/Tasks";
import { Timeline } from "./screens/Timeline";
import type { User } from "./types";

function useHashRoute(): string {
  const read = () => window.location.hash.replace(/^#/, "") || "/home";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function App() {
  const [signedIn, setSignedIn] = useState(isSignedIn());
  const [user, setUser] = useState<User | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const route = useHashRoute();
  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);
  const clearToast = useCallback(() => setToast(null), []);

  useEffect(() => {
    const onSignedOut = () => {
      setSignedIn(false);
      setUser(null);
    };
    window.addEventListener("pos:signed-out", onSignedOut);
    return () => window.removeEventListener("pos:signed-out", onSignedOut);
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    api<User>("/v1/me").then(setUser).catch(() => undefined);
    const sync = () =>
      flushQueue().then((count) => {
        if (count) {
          setToast(`Synced ${count} saved entr${count > 1 ? "ies" : "y"}.`);
          refresh();
        }
      });
    sync();
    // Entries waiting for the network or a busy AI go out again without reopening the app.
    const timer = window.setInterval(() => {
      if (pendingCaptures().length) sync();
    }, 60_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") sync();
    };
    window.addEventListener("online", sync);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", sync);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [signedIn, refresh]);

  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;

  const [, section, param] = route.split("/");
  let screen;
  // Pages for managing things open from Me, so that tab stays highlighted on them.
  let tab = section || "home";
  if (section === "event" && param) {
    screen = <EventDetail key={param} id={param} notify={setToast} onChanged={refresh} />;
    tab = "timeline";
  } else if (section === "project" && param) {
    screen = <Project key={param} id={param} notify={setToast} />;
    tab = "me";
  } else if (section === "goal" && param) {
    screen = <Goal key={param} id={param} notify={setToast} />;
    tab = "me";
  } else if (section === "habit" && param) {
    screen = <Habit key={param} id={param} notify={setToast} />;
    tab = "me";
  } else if (section === "knowledge" && param) {
    screen = <Knowledge key={param} id={param} notify={setToast} />;
    tab = "me";
  } else if (section === "deleted") {
    screen = <Deleted notify={setToast} onChanged={refresh} />;
    tab = "me";
  } else if (section === "shortcuts") {
    screen = <Shortcuts notify={setToast} />;
    tab = "me";
  } else if (section === "tasks") {
    screen = <Tasks notify={setToast} />;
    tab = "home";
  } else if (section === "timeline") screen = <Timeline refreshKey={refreshKey} />;
  else if (section === "insights") screen = <Insights />;
  else if (section === "me") screen = <Me user={user} onUser={setUser} notify={setToast} />;
  else {
    screen = <Home user={user} onCapture={() => setCapturing(true)} refreshKey={refreshKey} notify={setToast} />;
    tab = "home";
  }

  return (
    <div className="app">
      {screen}
      <TabBar current={tab} />
      {capturing && <CaptureSheet language={user?.locale ?? "en"} onClose={() => setCapturing(false)} onSaved={refresh} />}
      {toast && <Toast text={toast} onDone={clearToast} />}
    </div>
  );
}
