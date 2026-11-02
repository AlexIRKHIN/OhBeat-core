import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { LoadingState, NotFoundPage } from "./components/ui";
import { BillingPage } from "./pages/BillingPage";
import { BeatPage } from "./pages/BeatPage";
import { CartPage } from "./pages/CartPage";
import { CheckoutPage } from "./pages/CheckoutPage";
import { CatalogPage } from "./pages/CatalogPage";
import { LegalPage } from "./pages/LegalPage";
import { LoginPage } from "./pages/LoginPage";
import { MyBeatsPage } from "./pages/MyBeatsPage";
import { OrderPage } from "./pages/OrderPage";
import { PaymentReturnPage } from "./pages/PaymentReturnPage";
import { ProducerConnectPage } from "./pages/ProducerConnectPage";
import { ProducerPage } from "./pages/ProducerPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";
import { UploadBeatPage } from "./pages/UploadBeatPage";

/** Pages for signed-in users; a guest is sent to sign in and comes back afterwards.
 *  With `role`, a user without it is sent to connect to sales (FR-33: no publishing without the Producer role). */
function RequireAuth({ children, role }: { children: ReactNode; role?: "producer" }) {
  const { user, loading, hasRole } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingState />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (role && !hasRole(role)) return <Navigate to="/producer/connect" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<CatalogPage />} />
        <Route path="/beats/:id" element={<BeatPage />} />
        <Route path="/producers/:id" element={<ProducerPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
        <Route path="/billing" element={<RequireAuth><BillingPage /></RequireAuth>} />
        <Route path="/cart" element={<RequireAuth><CartPage /></RequireAuth>} />
        <Route path="/checkout" element={<RequireAuth><CheckoutPage /></RequireAuth>} />
        <Route path="/orders/:id" element={<RequireAuth><OrderPage /></RequireAuth>} />
        <Route path="/orders/:id/return" element={<RequireAuth><PaymentReturnPage /></RequireAuth>} />
        <Route path="/producer/connect" element={<RequireAuth><ProducerConnectPage /></RequireAuth>} />
        <Route path="/producer/beats" element={<RequireAuth role="producer"><MyBeatsPage /></RequireAuth>} />
        <Route path="/producer/beats/new" element={<RequireAuth role="producer"><UploadBeatPage /></RequireAuth>} />
        <Route path="/legal/:doc" element={<LegalPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Layout>
  );
}
