import { History } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SafetyTransition } from "../../api/client";
import { Badge } from "../../components/ui/Badge";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/StateView";
import { formatDateTime } from "../../lib/format";
import { safetyLabel, safetyTone, sourceLabel } from "../../lib/labels";

export function SafetyHistory({ items }: { items: SafetyTransition[] }) {
  const { t } = useTranslation();
  return (
    <Card title={t("history.title")} labelledBy="history-title">
      {items.length === 0 ? (
        <EmptyState icon={<History size={22} />} title={t("history.empty")} description={t("history.emptyDesc")} />
      ) : (
        <div className="table-wrap" tabIndex={0} aria-labelledby="history-title" role="region">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("history.time")}</th>
                <th scope="col">{t("history.transition")}</th>
                <th scope="col">{t("history.reason")}</th>
                <th scope="col">{t("history.source")}</th>
                <th scope="col">{t("history.actor")}</th>
              </tr>
            </thead>
            <tbody>
              {[...items].reverse().map((tr) => (
                <tr key={tr.transition_id}>
                  <td className="num">{formatDateTime(tr.at)}</td>
                  <td>
                    <Badge tone={safetyTone[tr.from_state]}>{safetyLabel(t, tr.from_state)}</Badge>
                    <span aria-hidden="true"> → </span>
                    <span className="sr-only">→</span>
                    <Badge tone={safetyTone[tr.to_state]}>{safetyLabel(t, tr.to_state)}</Badge>
                  </td>
                  {/* Mã lý do do người dùng nhập: hiển thị nguyên văn, không dịch. */}
                  <td className="mono">{tr.reason_code}</td>
                  <td>{sourceLabel(t, tr.trigger_source)}</td>
                  <td>{tr.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
