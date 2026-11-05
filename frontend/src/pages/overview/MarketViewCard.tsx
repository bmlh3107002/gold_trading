import { CandlestickChart } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MarketView } from "../../api/client";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber, formatPercent } from "../../lib/format";
import { biasLabel, biasTone, regimeLabel } from "../../lib/labels";

function Item({ label, tip, children }: { label: string; tip?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="kv__label">
        {label}
        {tip && <InfoTip label={label} text={tip} />}
      </div>
      <div className="kv__value">{children}</div>
    </div>
  );
}

export function MarketViewCard({ view }: { view: MarketView | null | undefined }) {
  const { t } = useTranslation();
  return (
    <Card
      title={t("marketView.title")}
      labelledBy="mv-title"
      actions={view && <Badge tone={biasTone[view.bias]}>{biasLabel(t, view.bias)}</Badge>}
    >
      {!view ? (
        <EmptyState
          icon={<CandlestickChart size={22} />}
          title={t("marketView.emptyTitle")}
          description={t("marketView.emptyDesc")}
        />
      ) : (
        <div className="kv">
          <Item label={t("marketView.pUp")} tip={t("marketView.pTip")}>
            <span className="tone-profit">{formatPercent(view.p_up)}</span>
          </Item>
          <Item label={t("marketView.pDown")} tip={t("marketView.pTip")}>
            <span className="tone-loss">{formatPercent(view.p_down)}</span>
          </Item>
          <Item label={t("marketView.confidence")} tip={t("marketView.confidenceTip")}>
            {formatPercent(view.confidence)}
          </Item>
          <Item label={t("marketView.regime")} tip={t("marketView.regimeTip")}>
            {regimeLabel(t, view.regime)}
          </Item>
          <Item label={t("marketView.volForecast")} tip={t("marketView.volTip")}>
            {formatNumber(view.vol_forecast)}
          </Item>
          <Item label={t("marketView.riskFlags")}>
            {view.risk_flags && view.risk_flags.length > 0 ? (
              <span className="mono">{view.risk_flags.join(", ")}</span>
            ) : (
              <span className="tone-neutral">{t("marketView.noFlags")}</span>
            )}
          </Item>
          <Item label={t("marketView.asOf")}>{formatDateTime(view.as_of)}</Item>
          <Item label={t("marketView.expiresAt")}>{formatDateTime(view.expires_at)}</Item>
        </div>
      )}
    </Card>
  );
}
