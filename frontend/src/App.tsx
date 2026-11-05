import { useCallback, useState } from "react";
import { Header } from "./components/layout/Header";
import { Sidebar } from "./components/layout/Sidebar";
import { useMarketSummary } from "./hooks/useMarket";
import { useRoute } from "./hooks/useRoute";
import { useSystemStatus } from "./hooks/useSystemStatus";
import { useTheme } from "./hooks/useTheme";
import { MarketPage } from "./pages/MarketPage";
import { OverviewPage } from "./pages/OverviewPage";

export default function App() {
  const sys = useSystemStatus();
  const market = useMarketSummary();
  const route = useRoute();
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
