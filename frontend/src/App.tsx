/**
 * 路由表（spec 第 4 节页面与交互）。
 * 全部路由都在同一个 React SPA 内，react-router 负责切换。
 */

import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/Layout";
import { ToastProvider } from "./components/ui";
import { SessionProvider } from "./state/SessionContext";
import { AtlasPage } from "./pages/AtlasPage";
import { BrandInsightsPage } from "./pages/BrandInsightsPage";
import { CabinetPage } from "./pages/CabinetPage";
import { ChatPage } from "./pages/ChatPage";
import { EnvironmentPage } from "./pages/EnvironmentPage";
import { HomePage } from "./pages/HomePage";
import { ImportPage } from "./pages/ImportPage";
import { InboxPage } from "./pages/InboxPage";
import { MemoryPage } from "./pages/MemoryPage";
import { ProductPage } from "./pages/ProductPage";
import { RoutinePage } from "./pages/RoutinePage";
import { ServicePage } from "./pages/ServicePage";
import { SettingsPage } from "./pages/SettingsPage";
import { StaffQueuePage, StaffTicketPage } from "./pages/StaffTicketPage";

function NotFoundPage(): JSX.Element {
  return (
    <div className="panel stack">
      <h1>页面不存在</h1>
      <p>没有匹配这个地址的路由。可以回到首页继续演示。</p>
      <div className="row tight">
        <Link className="btn primary" to="/">
          返回首页
        </Link>
      </div>
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <ToastProvider>
      <SessionProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/cabinet" element={<CabinetPage />} />
              <Route path="/imports/:id" element={<ImportPage />} />
              <Route path="/products/:ownedId" element={<ProductPage />} />
              <Route path="/routine" element={<RoutinePage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/service" element={<ServicePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/environment" element={<EnvironmentPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/brand/insights" element={<BrandInsightsPage />} />
              {/* 演示客服视图：:id 为必需路由，队列页方便进入具体工单 */}
              <Route path="/staff/tickets" element={<StaffQueuePage />} />
              <Route path="/staff/tickets/:id" element={<StaffTicketPage />} />
              <Route path="/ingredients/atlas" element={<AtlasPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </ToastProvider>
  );
}
