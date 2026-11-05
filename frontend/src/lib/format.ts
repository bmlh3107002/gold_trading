const LOCALE = "vi-VN";

const num2 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct1 = new Intl.NumberFormat(LOCALE, {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const dateTime = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const time = new Intl.DateTimeFormat(LOCALE, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export const EMPTY = "—";

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return EMPTY;
  if (digits === 2) return num2.format(value);
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** value là tỷ lệ 0..1 */
export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return EMPTY;
  return pct1.format(value);
}

/** Số tiền kèm đơn vị (USD/USDT không phải lúc nào cũng là mã ISO nên ghép thủ công). */
export function formatMoney(value: number | null | undefined, unit = "USD"): string {
  if (value == null || !Number.isFinite(value)) return EMPTY;
  return `${num2.format(value)} ${unit}`;
}

export function formatSignedMoney(value: number | null | undefined, unit = "USD"): string {
  if (value == null || !Number.isFinite(value)) return EMPTY;
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatMoney(value, unit)}`;
}

export type Tone = "profit" | "loss" | "neutral";

export function pnlTone(value: number | null | undefined): Tone {
  if (value == null || !Number.isFinite(value) || value === 0) return "neutral";
  return value > 0 ? "profit" : "loss";
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (value == null) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? dateTime.format(d) : EMPTY;
}

export function formatTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? time.format(d) : EMPTY;
}
