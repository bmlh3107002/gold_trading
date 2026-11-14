import { AlertTriangle, Gauge } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AnalystLatest } from "../../api/client";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { InfoTip } from "../../components/ui/InfoTip";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/StateView";
import { formatDateTime, formatNumber } from "../../lib/format";
import { readRegime } from "../../lib/regime";

interface Props {
  data: AnalystLatest | null;
  loading: boolean;
  onRetry: () => void;
}

const tone: Record<string, BadgeTone> = { TREND: "gold", RANGE: "neutral", HIGH_VOL: "loss" };

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

export function RegimeCard({ data, loading, onRetry }: Props) {
  const { t } = useTranslation();
  const out = data?.output ?? null;
  const blocked = !!out && out.source_status !== "HEALTHY";
  const status = !out ? null : blocked ? "blocked" : data?.valid_now ? "valid" : "expired";
  const statusTone: BadgeTone = status === "valid" ? "profit" : status === "expired" ? "gold" : "loss";
  const f = readRegime(out?.features as Record<string, unknown> | undefined);

  return (
    <Card
      title={
        <>
          <Gauge size={15} aria-hidden="true" />
          {t("regime.title")}
        </>
      }
      description={t("regime.desc")}
      labelledBy="regime-title"
      actions={status && <Badge tone={statusTone} dot>{t(`regime.status.${status}`)}</Badge>}
    >
      {!data && loading && <LoadingState label={t("regime.loading")} />}
      {!data && !loading && <ErrorState title={t("regime.errorTitle")} retryLabel={t("market.retry")} onRetry={onRetry} />}
      {data && !out && (
        <EmptyState
          icon={<Gauge size={22} />}
          title={t("regime.emptyTitle")}
          description={data.is_sample || data.computed_at ? t("regime.emptyDesc") : t("regime.noSource")}
        />
      )}
      {out && blocked && (
        <div className="banner banner--error" role="alert" style={{ marginBottom: 12 }}>
          <AlertTriangle size={16} className="tone-loss" aria-hidden="true" />
          <div className="banner__body">
            <div className="banner__title">{t("regime.blockedTitle")}</div>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {out.drivers.map((d) => (
                <li key={d} className="mono">
                  {d}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {out && status === "expired" && (
        <div className="banner banner--warn" role="status" style={{ marginBottom: 12 }}>
          <div className="banner__body">{t("regime.expiredDesc")}</div>
        </div>
      )}
      {out && !blocked && (
        <div className="kv" style={{ marginBottom: 12 }}>
          <Item label={t("regime.label")}>
            {f.regime ? (
              <>
                <Badge tone={tone[f.regime]}>
                  {t(`regime.value.${f.regime}`)}
                  {f.direction ? ` · ${t(`regime.direction.${f.direction}`)}` : ""}
                </Badge>
                {f.ambiguous && <div className="metric__hint">{t("regime.ambiguous")}</div>}
              </>
            ) : (
              "—"
            )}
          </Item>
          <Item label={t("regime.adx")} tip={t("regime.adxTip")}>
            <span className="num">{formatNumber(f.adx14, 1)}</span>
          </Item>
          <Item label={t("regime.vol")} tip={t("regime.volTip")}>
            <span className={`num ${f.vol_ratio != null && f.vol_ratio >= 2 ? "tone-loss" : ""}`}>
              {f.vol_ratio != null ? `${formatNumber(f.vol_ratio)}×` : "—"}
            </span>
          </Item>
          <Item label={t("regime.since")}>
            {f.bars_in_regime == null
              ? "—"
              : f.bars_in_regime_capped
                ? t("regime.sinceCapped", { n: f.bars_in_regime })
                : t("regime.sinceValue", {
                    n: f.bars_in_regime,
                    time: formatDateTime(f.regime_since),
                    prev: f.previous_regime ? t(`regime.value.${f.previous_regime}`) : "—",
                  })}
          </Item>
        </div>
      )}
      {out && (
        <>
          {!blocked && f.risk_off === "NOT_EVALUATED" && <p className="card__desc">{t("regime.riskOff")}</p>}
          {!blocked && !f.weights_calibrated && <p className="card__desc">{t("regime.weightsNote")}</p>}
          <div className="kv" style={{ margin: "10px 0" }}>
            <Item label={t("regime.asOf")}>{formatDateTime(out.as_of)}</Item>
            <Item label={t("regime.expiresAt")}>{formatDateTime(out.expires_at)}</Item>
          </div>
          <p className="card__desc">
            {t("regime.confidenceNote")} · {t("regime.version")}: <span className="mono">{out.version}</span>
          </p>
        </>
      )}
    </Card>
  );
}
