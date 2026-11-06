import { Check, Lock, OctagonX, Pause, Play, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { AccountStatus, ApiError, LiveRequest, Perm, SafetyCommand, TradingMode } from "../../api/client";
import { Button, IconButton } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Dialog } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { formatTime } from "../../lib/format";
import { modeLabel } from "../../lib/labels";

const MODES: TradingMode[] = ["BACKTEST", "PAPER", "SHADOW", "LIVE"];

type Action = SafetyCommand["action"];
type Pending = { kind: "halt" } | { kind: "resumeHalted" } | { kind: "live" } | null;

interface ControlPanelProps {
  status: AccountStatus;
  disabled: boolean;
  me: string;
  liveRequests: LiveRequest[];
  onSafety: (cmd: SafetyCommand) => Promise<ApiError | null>;
  onMode: (mode: TradingMode) => Promise<ApiError | null>;
  onRequestLive: () => Promise<ApiError | null>;
  onApproveLive: (requestId: string) => Promise<ApiError | null>;
}

export function ControlPanel({
  status,
  disabled,
  me,
  liveRequests,
  onSafety,
  onMode,
  onRequestLive,
  onApproveLive,
}: ControlPanelProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [approved, setApproved] = useState(false);

  // Người thao tác lấy từ phiên đăng nhập ở backend, không nhập tay.
  const locked = disabled || busy;
  // Giao diện chỉ ẩn/khóa nút cho dễ dùng; backend vẫn kiểm quyền mỗi request.
  const can = (p: Perm) => status.permissions.includes(p);
  const readOnly = !can("PAUSE_HALT") && !can("SET_MODE");

  async function exec(fn: () => Promise<ApiError | null>, context: "safety" | "mode") {
    setBusy(true);
    setError(null);
    const err = await fn();
    setBusy(false);
    if (err) {
      setError(
        err.kind === "conflict"
          ? t(context === "safety" ? "errors.safetyConflict" : "errors.modeConflict")
          : t(`errors.${err.kind}`),
      );
    }
    return err;
  }

  function sendSafety(action: Action, operator_approved = false) {
    // Giữ nguyên quy ước cũ: để trống lý do -> MANUAL_<ACTION>.
    const reason_code = reason.trim() || `MANUAL_${action.toUpperCase()}`;
    return exec(() => onSafety({ action, reason_code, operator_approved }), "safety");
  }

  function request(action: Action) {
    if (action === "halt") return setPending({ kind: "halt" });
    if (action === "resume" && status.safety_state === "HALTED") {
      setApproved(false);
      return setPending({ kind: "resumeHalted" });
    }
    void sendSafety(action);
  }

  function requestMode(mode: TradingMode) {
    if (mode === "LIVE") return setPending({ kind: "live" });
    void exec(() => onMode(mode), "mode");
  }

  async function confirm() {
    const p = pending;
    setPending(null);
    if (p?.kind === "halt") await sendSafety("halt");
    else if (p?.kind === "resumeHalted") await sendSafety("resume", true);
    else if (p?.kind === "live") await exec(onRequestLive, "mode");
  }

  const s = status.safety_state;
  const dialog =
    pending?.kind === "halt"
      ? { title: t("dialog.haltTitle"), desc: t("dialog.haltDesc"), confirm: t("dialog.haltConfirm"), danger: true }
      : pending?.kind === "resumeHalted"
        ? {
            title: t("dialog.resumeHaltedTitle"),
            desc: t("dialog.resumeHaltedDesc"),
            confirm: t("dialog.resumeConfirm"),
            danger: false,
          }
        : pending?.kind === "live"
          ? { title: t("dialog.liveTitle"), desc: t("dialog.liveDesc"), confirm: t("dialog.liveConfirm"), danger: true }
          : null;

  return (
    <Card title={t("controls.title")} description={t("controls.desc")} labelledBy="controls-title">
      {disabled && (
        <div className="banner banner--warn" style={{ marginBottom: 14 }} role="status">
          <span className="banner__body">{t("controls.disconnected")}</span>
        </div>
      )}
      {error && (
        <div className="banner banner--error" style={{ marginBottom: 14 }} role="alert">
          <span className="banner__body">{error}</span>
          <IconButton label={t("errors.dismiss")} onClick={() => setError(null)}>
            <X size={14} aria-hidden="true" />
          </IconButton>
        </div>
      )}

      {readOnly && (
        <div className="banner banner--info" style={{ marginBottom: 14 }} role="status">
          <span className="banner__body">{t("controls.readOnly")}</span>
        </div>
      )}

      <div className="form-grid">
        <Field
          label={t("controls.reason")}
          hint={t("controls.reasonHint")}
          placeholder={t("controls.reasonPlaceholder")}
          value={reason}
          maxLength={64}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>

      <div className="control-group">
        <span className="control-group__label">{t("controls.safetyGroup")}</span>
        <div className="btn-row">
          <Button
            variant="primary"
            icon={<Play size={14} aria-hidden="true" />}
            disabled={locked || s === "ACTIVE" || !can(s === "HALTED" ? "EXIT_HALTED" : "RESUME")}
            onClick={() => request("resume")}
          >
            {t("controls.resume")}
          </Button>
          <Button
            variant="secondary"
            icon={<Pause size={14} aria-hidden="true" />}
            disabled={locked || s !== "ACTIVE" || !can("PAUSE_HALT")}
            onClick={() => request("pause")}
          >
            {t("controls.pause")}
          </Button>
          <Button
            variant="danger"
            icon={<OctagonX size={14} aria-hidden="true" />}
            disabled={locked || s === "HALTED" || !can("PAUSE_HALT")}
            onClick={() => request("halt")}
          >
            {t("controls.halt")}
          </Button>
        </div>
      </div>

      <div className="control-group">
        <span className="control-group__label" id="mode-group">
          {t("controls.modeGroup")}
        </span>
        <div className="segmented" role="group" aria-labelledby="mode-group">
          {MODES.map((m) => {
            const isLocked = m === "LIVE" && !status.live_unlocked;
            return (
              <button
                key={m}
                type="button"
                className="segmented__item"
                aria-pressed={m === status.mode}
                disabled={locked || m === status.mode || !can(m === "LIVE" ? "REQUEST_LIVE" : "SET_MODE")}
                onClick={() => requestMode(m)}
                title={isLocked ? t("controls.locked") : undefined}
              >
                {isLocked && <Lock size={12} aria-hidden="true" />}
                {modeLabel(t, m)}
                {isLocked && <span className="sr-only">({t("controls.locked")})</span>}
              </button>
            );
          })}
        </div>
      </div>

      {liveRequests.length > 0 && (
        <div className="control-group">
          <span className="control-group__label">{t("controls.livePending")}</span>
          {liveRequests.map((r) => (
            <div key={r.request_id} className="banner banner--warn" role="status">
              <span className="banner__body">
                {t("controls.livePendingItem", {
                  name: r.requested_by,
                  time: formatTime(new Date(r.expires_at)),
                })}
              </span>
              {can("APPROVE_LIVE") && r.requested_by !== me ? (
                <Button
                  variant="danger"
                  icon={<Check size={14} aria-hidden="true" />}
                  disabled={locked}
                  onClick={() => void exec(() => onApproveLive(r.request_id), "mode")}
                >
                  {t("controls.liveApprove")}
                </Button>
              ) : (
                <span className="header__label">{t("controls.liveNeedsOther")}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog
        open={dialog !== null}
        title={dialog?.title ?? ""}
        description={dialog?.desc}
        closeLabel={t("dialog.close")}
        onClose={() => setPending(null)}
        actions={
          <>
            <Button variant="secondary" data-autofocus onClick={() => setPending(null)}>
              {t("dialog.cancel")}
            </Button>
            <Button
              variant={dialog?.danger ? "danger" : "primary"}
              disabled={pending?.kind === "resumeHalted" && !approved}
              onClick={() => void confirm()}
            >
              {dialog?.confirm}
            </Button>
          </>
        }
      >
        {pending?.kind === "resumeHalted" && (
          <label className="check">
            <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
            <span>{t("dialog.resumeHaltedCheck")}</span>
          </label>
        )}
      </Dialog>
    </Card>
  );
}
