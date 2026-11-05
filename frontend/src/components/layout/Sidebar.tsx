import {
  BookOpenText,
  CandlestickChart,
  LayoutDashboard,
  ListOrdered,
  ShieldAlert,
  X,
} from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { GatewayStatus } from "../../api/client";
import type { Route } from "../../hooks/useRoute";
import type { ConnectionState } from "../../lib/connection";
import { IconButton } from "../ui/Button";
import { connectionTone } from "./ConnectionBadge";
import { Logo } from "./Logo";

const PAGES = [
  { key: "overview", icon: LayoutDashboard },
  { key: "market", icon: CandlestickChart },
] as const;

const SOON = [
  { key: "orders", icon: ListOrdered },
  { key: "risk", icon: ShieldAlert },
  { key: "journal", icon: BookOpenText },
] as const;

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  connection: ConnectionState;
  version: string | null;
  storage: string | null;
  route: Route;
  gateway: GatewayStatus | null;
}

export function Sidebar({ open, onClose, connection, version, storage, route, gateway }: SidebarProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    ref.current?.querySelector<HTMLElement>("a, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const tone = connectionTone[connection];
  return (
    <>
      <div className="drawer-backdrop" data-open={open} onClick={onClose} aria-hidden="true" />
      <aside ref={ref} className="sidebar" data-open={open} aria-label={t("app.name")}>
        <div className="sidebar__brand">
          <Logo />
          {open && (
            <IconButton label={t("nav.closeMenu")} onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </IconButton>
          )}
        </div>
        <nav className="nav" aria-label={t("nav.sectionMain")}>
          <div className="nav__section">{t("nav.sectionMain")}</div>
          {PAGES.map(({ key, icon: Icon }) => (
            <a
              key={key}
              className="nav__item"
              href={`#${key}`}
              aria-current={route === key ? "page" : undefined}
              onClick={onClose}
            >
              <Icon size={17} aria-hidden="true" />
              {t(`nav.${key}`)}
            </a>
          ))}
          <div className="nav__section">{t("nav.sectionSoon")}</div>
          {SOON.map(({ key, icon: Icon }) => (
            <span
              key={key}
              className="nav__item"
              aria-disabled="true"
              title={t("nav.soonHint")}
            >
              <Icon size={17} aria-hidden="true" />
              {t(`nav.${key}`)}
              <span className="nav__soon">{t("nav.soon")}</span>
            </span>
          ))}
        </nav>
        <div className="sidebar__footer">
          <span className="header__label">{t("system.title")}</span>
          <span className={`sidebar__status tone-${tone}`}>
            <span className="dot" aria-hidden="true" />
            {t(`connection.${connection}`)}
          </span>
          <span className="header__label">
            {version ? t("system.backend", { version }) : t("system.backendUnknown")}
          </span>
          {gateway && (
            <span
              className={`sidebar__status tone-${
                gateway.state === "CONNECTED" ? "profit" : gateway.state === "NEVER" ? "neutral" : "loss"
              }`}
            >
              <span className="dot" aria-hidden="true" />
              {t(`system.gateway.${gateway.state}`)}
              {gateway.heartbeat && ` · ${t(`system.gateway.account.${gateway.heartbeat.account_type}`)}`}
            </span>
          )}
          {storage && (
            <span className={`header__label ${storage === "memory" ? "tone-gold" : ""}`}>
              {storage === "postgres" || storage === "memory"
                ? t(`system.storage.${storage}`)
                : t("system.storage.other", { kind: storage })}
            </span>
          )}
        </div>
      </aside>
    </>
  );
}
