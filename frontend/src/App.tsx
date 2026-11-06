import { useCallback, useState } from "react";
import { Header } from "./components/layout/Header";
import { Sidebar } from "./components/layout/Sidebar";
import { useGatewayStatus, useMarketSummary } from "./hooks/useMarket";
import { useRoute } from "./hooks/useRoute";
import { useSystemStatus } from "./hooks/useSystemStatus";
import { useTheme } from "./hooks/useTheme";
import { useAuth } from "./hooks/useAuth";
import type { Me } from "./api/client";
import { ErrorState, LoadingState } from "./components/ui/StateView";
import { LoginPage } from "./pages/LoginPage";
import { MarketPage } from "./pages/MarketPage";
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
  const sys = useSystemStatus();
  const market = useMarketSummary();
  const route = useRoute();
  const gateway = useGatewayStatus(sys.status?.data_source === "MT5");
  const { theme, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  return (
    <div className="app">
      <Sidebar
        open={menuOpen}
        onClose={closeMenu}
        connection={sys.connection}
        version={sys.status?.version ?? null}
        storage={sys.status?.storage ?? null}
        route={route}
        gateway={sys.status?.data_source === "MT5" ? gateway.data : null}
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
        />
        <main>
          {route === "market" ? (
            <MarketPage theme={theme} summary={market} />
          ) : (
            <OverviewPage sys={sys} />
          )}
        </main>
      </div>
    </div>
  );
}
