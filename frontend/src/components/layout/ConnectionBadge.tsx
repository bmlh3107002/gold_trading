import { useTranslation } from "react-i18next";
import type { ConnectionState } from "../../lib/connection";
import { Badge, type BadgeTone } from "../ui/Badge";

const tone: Record<ConnectionState, BadgeTone> = {
  live: "profit",
  connecting: "info",
  stale: "gold",
  disconnected: "loss",
};

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  const { t } = useTranslation();
  return (
    <span role="status" aria-live="polite">
      <Badge tone={tone[state]} dot>
        {t(`connection.${state}`)}
      </Badge>
    </span>
  );
}

export const connectionTone = tone;
