import type { ReactNode } from "react";

export type BadgeTone = "profit" | "loss" | "gold" | "info" | "neutral";

export function Badge({
  tone = "neutral",
  dot,
  children,
}: {
  tone?: BadgeTone;
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`badge ${tone !== "neutral" ? `badge--${tone}` : ""}`}>
      {dot && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
