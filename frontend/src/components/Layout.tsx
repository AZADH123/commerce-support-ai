import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export function Layout() {
  const { user, signOut } = useAuth();
  const isReviewer = user?.role === "reviewer";

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">🛟 Commerce Support</span>
        <nav className="app-nav" aria-label="Primary">
          <NavLink to="/chat" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            Chat
          </NavLink>
          <NavLink to="/cases" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            My cases
          </NavLink>
          {isReviewer && (
            <NavLink to="/review" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              Review queue
            </NavLink>
          )}
        </nav>
        <div className="app-user">
          {user && <span className="app-user-name">{user.name}</span>}
          <button type="button" className="button button-ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

export function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="page">
      <h1>{title}</h1>
      {children}
    </section>
  );
}
