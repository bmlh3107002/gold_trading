import { useTranslation } from "react-i18next";
import type { SystemStatus } from "../../api/client";
import { InfoTip } from "../../components/ui/InfoTip";
import { SkeletonMetric } from "../../components/ui/StateView";
import { biasLabel, biasTone, modeLabel, safetyLabel, safetyTone } from "../../lib/labels";

function Metric({
  label,
  tip,
  children,
  hint,
}: {
  label: string;
  tip?: string;
  children: React.ReactNode;
  hint?: React.ReactNode;
}) {
  return (
    <section className="card" aria-label={label}>
      <div className="metric__label">
        {label}
        {tip && <InfoTip label={label} text={tip} />}
      </div>
      <div className="metric__value">{children}</div>
      {hint && <div className="metric__hint">{hint}</div>}
    </section>
  );
}

export function MetricCards({ status }: { status: SystemStatus | null }) {
  const { t } = useTranslation();
  if (!status) {
    return (
      <div className="grid-4">
        {[0, 1, 2, 3].map((i) => (
          <div className="card" key={i}>
            <SkeletonMetric />
          </div>
        ))}
      </div>
    );
  }
  const view = status.market_view;
  return (
    <div className="grid-4">
      <Metric
        label={t("metric.safety")}
        tip={t("metric.safetyTip")}
        hint={t(`metric.safetyHint.${status.safety_state}`)}
      >
        <span className={`tone-${safetyTone[status.safety_state]}`}>
          {safetyLabel(t, status.safety_state)}
        </span>
      </Metric>
      <Metric
        label={t("metric.mode")}
        tip={t("metric.modeTip")}
        hint={status.live_unlocked ? t("metric.liveUnlocked") : t("metric.liveLocked")}
      >
        <span className={status.mode === "LIVE" ? "tone-loss" : undefined}>
          {modeLabel(t, status.mode)}
        </span>
      </Metric>
      <Metric
        label={t("metric.orders")}
        hint={status.allows_new_orders ? t("metric.ordersAllowedHint") : t("metric.ordersBlockedHint")}
      >
        <span className={status.allows_new_orders ? "tone-profit" : "tone-loss"}>
          {status.allows_new_orders ? t("metric.ordersAllowed") : t("metric.ordersBlocked")}
        </span>
      </Metric>
      <Metric
        label={t("metric.bias")}
        tip={t("metric.biasTip")}
        hint={view ? undefined : t("metric.noViewHint")}
      >
        {view ? (
          <span className={`tone-${biasTone[view.bias]}`}>{biasLabel(t, view.bias)}</span>
        ) : (
          <span className="tone-neutral">{t("metric.noView")}</span>
        )}
      </Metric>
    </div>
  );
}
