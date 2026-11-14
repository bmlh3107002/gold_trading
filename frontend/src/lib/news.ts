/** Đọc an toàn features của analyst Tin tức (docs/thiet-ke/32). Sai kiểu → bỏ. */
export interface NewsItem {
  title: string;
  url: string | null;
  source: string | null;
  firstSeenAt: string | null;
  topics: string | null;
  assessed: boolean;
  goldImpact: "BULLISH" | "BEARISH" | "NEUTRAL" | "UNCLEAR" | null;
  impact: "LOW" | "MEDIUM" | "HIGH" | null;
  novelty: "ROUTINE" | "NOTABLE" | "SURPRISE" | null;
  quote: string | null;
  summaryVi: string | null;
  suspect: boolean;
}

export interface NewsFeatures {
  mode: "LLM" | "RULES_ONLY" | null;
  items: NewsItem[];
  unassessed: NewsItem[];
  shock: boolean;
  tone: number | null;
  unprocessed: number;
  budget: { cap: string | null; spent: string | null } | null;
}

const str = (v: unknown) => (typeof v === "string" && v.length > 0 ? v : null);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;
const obj = (v: unknown) => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

function item(v: unknown): NewsItem | null {
  const o = obj(v);
  const title = o ? str(o.title) : null;
  if (!o || !title) return null;
  const url = str(o.url);
  return {
    title,
    url: url && /^https:\/\//.test(url) ? url : null,
    source: str(o.source),
    firstSeenAt: str(o.first_seen_at),
    topics: str(o.topics),
    assessed: o.assessed === true,
    goldImpact: oneOf(o.gold_impact, ["BULLISH", "BEARISH", "NEUTRAL", "UNCLEAR"] as const),
    impact: oneOf(o.impact, ["LOW", "MEDIUM", "HIGH"] as const),
    novelty: oneOf(o.novelty, ["ROUTINE", "NOTABLE", "SURPRISE"] as const),
    quote: str(o.evidence_quote),
    summaryVi: str(o.summary_vi),
    suspect: o.suspect_instructions === true,
  };
}

const items = (v: unknown) => (Array.isArray(v) ? v.map(item).filter((x): x is NewsItem => x !== null) : []);

export function readNews(features: Record<string, unknown> | undefined): NewsFeatures {
  const f = features ?? {};
  const b = obj(f.budget);
  return {
    mode: oneOf(f.mode, ["LLM", "RULES_ONLY"] as const),
    items: items(f.items),
    unassessed: items(f.unassessed),
    shock: f.news_shock === true,
    tone: num(f.tone_score),
    unprocessed: num(f.unprocessed) ?? 0,
    budget: b ? { cap: str(b.monthly_cap_usd), spent: str(b.spent_month_usd) } : null,
  };
}
