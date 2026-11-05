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
  return source === "dashboard" ? t("enum.source.dashboard") : t("enum.source.unknown");
}
