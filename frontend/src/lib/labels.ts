import type { TFunction } from "i18next";
import type { Tone } from "./format";

type BadgeTone = Tone | "gold" | "info";

export type SafetyState = "ACTIVE" | "PAUSED" | "HALTED";
export type Mode = "BACKTEST" | "PAPER" | "SHADOW" | "LIVE";
export type Bias = "LONG" | "SHORT" | "NEUTRAL";
export type Regime = "TREND" | "RANGE" | "RISK_OFF" | "HIGH_VOL";
export type PositionStatus = "OPEN" | "CLOSED" | "PARTIALLY_CLOSED";

export const safetyTone: Record<SafetyState, BadgeTone> = {
  ACTIVE: "profit",
  PAUSED: "gold",
  HALTED: "loss",
};

export const biasTone: Record<Bias, BadgeTone> = {
  LONG: "profit",
  SHORT: "loss",
  NEUTRAL: "neutral",
};

export const positionTone: Record<PositionStatus, BadgeTone> = {
  OPEN: "info",
  CLOSED: "neutral",
  PARTIALLY_CLOSED: "gold",
};

export function safetyLabel(t: TFunction, s: SafetyState): string {
  return t(`enum.safety.${s}`);
}
export function modeLabel(t: TFunction, m: Mode): string {
  return t(`enum.mode.${m}`);
}
export function biasLabel(t: TFunction, b: Bias): string {
  return t(`enum.bias.${b}`);
}
export function regimeLabel(t: TFunction, r: Regime): string {
  return t(`enum.regime.${r}`);
}
export function positionLabel(t: TFunction, p: PositionStatus): string {
  return t(`enum.position.${p}`);
}
export function sourceLabel(t: TFunction, source: string): string {
  if (source === "dashboard") return t("enum.source.dashboard");
  if (source === "startup") return t("enum.source.startup");
  return t("enum.source.unknown");
}

const KNOWN_QUARANTINE = new Set([
  "INVALID_OHLC",
  "BAR_NOT_CLOSED",
  "MISALIGNED_TIME",
  "NON_POSITIVE_PRICE",
  "NON_FINITE_PRICE",
  "NEGATIVE_VOLUME",
  "NAIVE_TIME",
  "BAD_TIME",
  "BAD_NUMBER",
  "AMBIGUOUS_LOCAL_TIME",
]);

export type DataSourceName = "SAMPLE" | "CSV" | "MT5";
export type CandleFlagName = "BACKFILL" | "REVISED" | "GAP_BEFORE" | "PRICE_JUMP" | "ZERO_RANGE";
export type Session = "OPEN" | "DAILY_BREAK" | "WEEKEND";

export function dataSourceLabel(t: TFunction, s: DataSourceName): string {
  return t(`enum.dataSource.${s}`);
}
export function flagLabel(t: TFunction, f: CandleFlagName): string {
  return t(`enum.flag.${f}`);
}
export function quarantineLabel(t: TFunction, reason: string): string {
  return KNOWN_QUARANTINE.has(reason)
    ? t(`enum.quarantine.${reason as "INVALID_OHLC"}`)
    : t("enum.quarantine.other");
}
export function sessionLabel(t: TFunction, s: Session): string {
  return t(`header.session.${s}`);
}
export const sessionTone: Record<Session, BadgeTone> = {
  OPEN: "profit",
  DAILY_BREAK: "gold",
  WEEKEND: "neutral",
};
