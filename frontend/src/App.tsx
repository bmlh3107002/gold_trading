import { useCallback, useState } from "react";
import { Header } from "./components/layout/Header";
import { OpsBanner } from "./components/layout/OpsBanner";
import { Sidebar } from "./components/layout/Sidebar";
import { useGatewayStatus, useMarketSummary } from "./hooks/useMarket";
import { useRoute } from "./hooks/useRoute";
import { useSystemStatus } from "./hooks/useSystemStatus";
import { useTheme } from "./hooks/useTheme";
import { useAuth } from "./hooks/useAuth";
import { useAccounts } from "./hooks/useAccounts";
import { usePolling } from "./hooks/usePolling";
import { api, type Me } from "./api/client";
import { ErrorState, LoadingState } from "./components/ui/StateView";
import { LoginPage } from "./pages/LoginPage";
import { MarketPage } from "./pages/MarketPage";
import { AccountPage } from "./pages/AccountPage";
import { AdminPage } from "./pages/AdminPage";
import { OverviewPage } from "./pages/OverviewPage";
import { useTranslation } from "react-i18next";

export default function App() {
  const { t } = useTranslation();
  const auth = useAuth();
  const s = auth.state;
  if (s.status === "loading") {
    return (
      <div className="login">
        <LoadingState label={t("auth.loading")} />
      </div>
    );
  }
  if (s.status === "error") {
    return (
      <div className="login">
        <ErrorState
          title={t("auth.loadError")}
          description={t("auth.loadErrorDesc")}
          retryLabel={t("overview.retry")}
          onRetry={() => void auth.reload()}
        />
      </div>
    );
  }
  if (s.status === "anonymous") return <LoginPage />;
  return <AuthedApp me={s.me} onLogout={() => void auth.logout()} />;
}

/** Chỉ dựng (và bắt đầu polling) khi đã đăng nhập. */
function AuthedApp({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const accounts = useAccounts();
  const accountId = accounts.selected?.account_id ?? null;
  const sys = useSystemStatus(accounts.loading ? null : accountId);
  const system = usePolling(api.system, 15_000, 60_000);
  const ops = usePolling(api.opsHealth, 30_000, 120_000);
  const market = useMarketSummary();
  const route = useRoute();
  const gateway = useGatewayStatus(system.data?.data_source === "MT5" ? accountId : null);
  const { theme, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  return (
    <div className="app">
      <Sidebar
        open={menuOpen}
        onClose={closeMenu}
        connection={sys.connection}
        version={system.data?.version ?? null}
        storage={system.data?.storage ?? null}
        route={route}
        gateway={system.data?.data_source === "MT5" ? gateway.data : null}
        isAdmin={me.is_admin}
      />
      <div className="main">
        <Header
          connection={sys.connection}
          lastSuccessAt={sys.lastSuccessAt}
          theme={theme}
          onToggleTheme={toggle}
          onOpenMenu={() => setMenuOpen(true)}
          menuOpen={menuOpen}
          market={market.data}
          userName={me.display_name || me.username}
          isAdmin={me.is_admin}
          onLogout={onLogout}
          accounts={accounts.list}
          selectedAccount={accountId}
          onSelectAccount={accounts.select}
        />
        <OpsBanner health={ops.data} />
        <main>
          {route === "market" ? (
            <MarketPage theme={theme} summary={market} />
          ) : route === "admin" ? (
            <AdminPage
              me={me}
              multiUser={system.data?.multi_user_enabled ?? true}
              onUserCreated={() => void accounts.refresh()}
            />
          ) : route === "account" ? (
            <AccountPage account={accounts.selected} me={me} />
          ) : (
            <OverviewPage sys={sys} accountId={accounts.loading ? null : accountId} me={me} />
          )}
        </main>
      </div>
    </div>
  );
}
