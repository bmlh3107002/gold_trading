import { LogOut, Menu, Moon, Sun, User } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AccountSummary, MarketSummary } from "../../api/client";
import type { Theme } from "../../hooks/useTheme";
import type { ConnectionState } from "../../lib/connection";
import { formatNumber, formatSignedPercent, formatTime, pnlTone } from "../../lib/format";
import { sessionLabel } from "../../lib/labels";
import { Badge } from "../ui/Badge";
import { IconButton } from "../ui/Button";
import { ConnectionBadge } from "./ConnectionBadge";

interface HeaderProps {
  connection: ConnectionState;
  lastSuccessAt: number | null;
  theme: Theme;
  onToggleTheme: () => void;
  onOpenMenu: () => void;
  menuOpen: boolean;
  market: MarketSummary | null;
  userName: string;
  isAdmin: boolean;
  onLogout: () => void;
  accounts: AccountSummary[];
  selectedAccount: string | null;
  onSelectAccount: (id: string) => void;
}

export function Header({
  connection,
  lastSuccessAt,
  theme,
  onToggleTheme,
  onOpenMenu,
  menuOpen,
  market,
  userName,
  isAdmin,
  onLogout,
  accounts,
  selectedAccount,
  onSelectAccount,
}: HeaderProps) {
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
        <span className="header__symbol header__hide-sm">{t("header.symbol")}</span>
        <div className="header__item header__hide-sm header__hide-md">
          <span className="header__label">{t("header.market")}</span>
          <span className="header__value tone-neutral">
            {market ? sessionLabel(t, market.session) : t("header.marketUnknown")}
          </span>
        </div>
        <div className="header__item header__item--price">
          <span className="header__label">
            <span className="header__hide-sm">{t("header.price")}</span>
            <span className="header__show-sm">{t("header.priceShort")}</span>
          </span>
          {market?.last_price != null ? (
            <span className="header__value num">
              {formatNumber(market.last_price)}
              {market.change != null && (
                <span className={`header__change tone-${pnlTone(market.change)}`}>
                  {" "}
                  {market.change > 0 ? "+" : ""}
                  {formatNumber(market.change)} ({formatSignedPercent(market.change_pct)})
                  <span className="sr-only"> {t("header.change24h")}</span>
                </span>
              )}
            </span>
          ) : (
            // Chưa có nguồn giá: không hiển thị số giả.
            <span className="header__value tone-neutral">
              <span className="header__hide-sm">{t("header.noPrice")}</span>
              <span className="header__show-sm">{t("header.noPriceShort")}</span>
            </span>
          )}
        </div>
        {market?.is_sample && (
          <span title={t("header.sampleTip")}>
            <Badge tone="gold">
              <span className="header__hide-sm">{t("header.sample")}</span>
              <span className="header__show-sm">{t("header.sampleShort")}</span>
            </Badge>
          </span>
        )}
        {market?.freshness === "STALE" && <Badge tone="loss">{t("header.priceStale")}</Badge>}
      </div>

      <div className="header__actions">
        {lastSuccessAt && (
          <span className="header__label header__hide-sm header__hide-md num">
            {t("connection.updatedAt", { time: formatTime(new Date(lastSuccessAt)) })}
          </span>
        )}
        {/* MT-19: chỉ có một tài khoản giao dịch thì tự dùng, không bắt chọn. */}
        {accounts.length > 1 && (
          <label className="header__account">
            <span className="sr-only">{t("accounts.label")}</span>
            <select
              className="header__select"
              value={selectedAccount ?? ""}
              onChange={(e) => onSelectAccount(e.target.value)}
              aria-label={t("accounts.label")}
            >
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <ConnectionBadge state={connection} />
        <span className="header__user header__hide-sm header__hide-md" title={t("auth.signedInAs", { name: userName })}>
          <User size={14} aria-hidden="true" />
          {userName}
          {isAdmin && <Badge tone="gold">{t("auth.admin")}</Badge>}
        </span>
        <IconButton label={t("auth.logout")} onClick={onLogout}>
          <LogOut size={17} aria-hidden="true" />
        </IconButton>
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
