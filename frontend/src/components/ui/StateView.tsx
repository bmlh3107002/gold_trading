import { AlertTriangle, Inbox, Loader2, RotateCw } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./Button";

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <Loader2 className="state__icon" size={22} aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="state">
      <span className="state__icon" aria-hidden="true">
        {icon ?? <Inbox size={22} />}
      </span>
      <p className="state__title">{title}</p>
      {description && <p className="state__desc">{description}</p>}
    </div>
  );
}

export function ErrorState({
  title,
  description,
  retryLabel,
  onRetry,
}: {
  title: string;
  description?: string;
  retryLabel?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state state--error" role="alert">
      <AlertTriangle className="state__icon" size={22} aria-hidden="true" />
      <p className="state__title">{title}</p>
      {description && <p className="state__desc">{description}</p>}
      {onRetry && retryLabel && (
        <Button variant="secondary" icon={<RotateCw size={14} aria-hidden="true" />} onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

export function SkeletonMetric() {
  return (
    <div aria-hidden="true">
      <div className="skeleton" style={{ width: "40%" }} />
      <div className="skeleton skeleton--value" />
    </div>
  );
}
