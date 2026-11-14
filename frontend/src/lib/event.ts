/** Đọc an toàn features của analyst Lịch sự kiện (docs/thiet-ke/28). Thiếu/sai kiểu → null / bỏ. */
export type EventRisk = "HIGH" | "MEDIUM" | "LOW" | "NONE";

export interface EventItem {
  event: string;
  title: string | null;
  importance: "HIGH" | "MEDIUM" | "LOW" | null;
  release_at: string;
  all_day: boolean;
  time_confirmed: boolean;
  minutes_until: number | null;
  actual_status: string | null;
  actuals: [string, string | null][];
  surprise_status: string | null;
}

export interface EventFeatures {
  event_risk: EventRisk | null;
  window: { start: string; end: string | null; reasons: string[] } | null;
  next_event: EventItem | null;
  soon: boolean;
  upcoming: EventItem[];
  recent_releases: EventItem[];
  removed: { event: string; release_at: string }[];
}

const str = (v: unknown) => (typeof v === "string" && v.length > 0 ? v : null);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;
const obj = (v: unknown) => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

function item(v: unknown): EventItem | null {
  const o = obj(v);
  if (!o) return null;
  const event = str(o.event);
  const release_at = str(o.release_at);
  if (!event || !release_at) return null;
  const actuals = Array.isArray(o.actuals)
    ? o.actuals.filter(
        (a): a is [string, string | null] =>
          Array.isArray(a) && a.length === 2 && typeof a[0] === "string" && (typeof a[1] === "string" || a[1] === null),
      )
    : [];
  return {
    event,
    title: str(o.title),
    importance: oneOf(o.importance, ["HIGH", "MEDIUM", "LOW"] as const),
    release_at,
    all_day: o.all_day === true,
    time_confirmed: o.time_confirmed === true,
    minutes_until: num(o.minutes_until),
    actual_status: str(o.actual_status),
    actuals,
    surprise_status: str(o.surprise_status),
  };
}

const items = (v: unknown) => (Array.isArray(v) ? v.map(item).filter((x): x is EventItem => x !== null) : []);

export function readEvent(features: Record<string, unknown> | undefined): EventFeatures {
  const f = features ?? {};
  const w = obj(f.window);
  const start = w ? str(w.start) : null;
  return {
    event_risk: oneOf(f.event_risk, ["HIGH", "MEDIUM", "LOW", "NONE"] as const),
    window:
      w && start
        ? {
            start,
            end: str(w.end),
            reasons: Array.isArray(w.reasons) ? w.reasons.filter((x): x is string => typeof x === "string") : [],
          }
        : null,
    next_event: item(f.next_event),
    soon: f.soon === true,
    upcoming: items(f.upcoming),
    recent_releases: items(f.recent_releases),
    removed: Array.isArray(f.removed)
      ? f.removed
          .map(obj)
          .filter((o): o is Record<string, unknown> => o !== null && !!str(o.event) && !!str(o.release_at))
          .map((o) => ({ event: o.event as string, release_at: o.release_at as string }))
      : [],
  };
}

/** Mã chặn của khung chung: "MISSING_INPUT:bls_schedule" → nhóm "MISSING_INPUT". */
export const blockingKind = (driver: string) => driver.split(":", 1)[0];
