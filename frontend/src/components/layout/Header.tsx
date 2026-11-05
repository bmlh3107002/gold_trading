import { Menu, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Theme } from "../../hooks/useTheme";
import type { ConnectionState } from "../../lib/connection";
import { formatTime } from "../../lib/format";
import { IconButton } from "../ui/Button";
import { ConnectionBadge } from "./ConnectionBadge";

interface HeaderProps {
  connection: ConnectionState;
  lastSuccessAt: number | null;
  theme: Theme;
  onToggleTheme: () => void;
  onOpenMenu: () => void;
  menuOpen: boolean;
}

export function Header({ connection, lastSuccessAt, theme, onToggleTheme, onOpenMenu, menuOpen }: HeaderProps) {
  const { t } = useTranslation();
  return (
    <header className="header">
      <IconButton
        className="header__menu"
        label={t("nav.openMenu")}
        aria-expanded={menuOpen}
        onClick={onOpenMenu}
      >
        <Menu size={18} aria-hidden="true" />
      </IconButton>

      <div className="header__ticker">
        <span className="header__symbol">{t("header.symbol")}</span>
        <div className="header__item header__hide-sm">
          <span className="header__label">{t("header.market")}</span>
          <span className="header__value tone-neutral">{t("header.marketUnknown")}</span>
        </div>
        <div className="header__item">
          <span className="header__label">{t("header.price")}</span>
          {/* Chưa có nguồn giá: không hiển thị số giả. */}
          <span className="header__value tone-neutral">
            <span className="header__hide-sm">{t("header.noPrice")}</span>
            <span className="header__show-sm">{t("header.noPriceShort")}</span>
          </span>
        </div>
      </div>

      <div className="header__actions">
        {lastSuccessAt && (
          <span className="header__label header__hide-sm num">
            {t("connection.updatedAt", { time: formatTime(new Date(lastSuccessAt)) })}
          </span>
        )}
        <ConnectionBadge state={connection} />
        <IconButton
          tone="gold"
          label={theme === "dark" ? t("header.toLight") : t("header.toDark")}
          onClick={onToggleTheme}
        >
          {theme === "dark" ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </IconButton>
      </div>
    </header>
  );
}
