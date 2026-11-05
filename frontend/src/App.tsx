import { useCallback, useState } from "react";
import { Header } from "./components/layout/Header";
import { Sidebar } from "./components/layout/Sidebar";
import { useSystemStatus } from "./hooks/useSystemStatus";
import { useTheme } from "./hooks/useTheme";
import { OverviewPage } from "./pages/OverviewPage";

export default function App() {
  const sys = useSystemStatus();
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
      />
      <div className="main">
        <Header
          connection={sys.connection}
          lastSuccessAt={sys.lastSuccessAt}
          theme={theme}
          onToggleTheme={toggle}
          onOpenMenu={() => setMenuOpen(true)}
          menuOpen={menuOpen}
        />
        <main>
          <OverviewPage sys={sys} />
        </main>
      </div>
    </div>
  );
}
