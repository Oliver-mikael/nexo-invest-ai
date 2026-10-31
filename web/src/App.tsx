import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom"
import { useEffect } from "react"
import { AuthProvider, RequireAuth } from "./lib/auth"
import { Shell } from "./components/Shell"
import { Landing } from "./pages/Landing"
import { Auth } from "./pages/Auth"
import { Dashboard } from "./pages/Dashboard"
import { Companies } from "./pages/Companies"
import { CompanyDetail } from "./pages/CompanyDetail"
import { Research } from "./pages/Research"
import { ResearchDetail } from "./pages/ResearchDetail"
import { Reports } from "./pages/Reports"
import { ReportDetail } from "./pages/ReportDetail"
import { Portfolio } from "./pages/Portfolio"
import { Settings } from "./pages/Settings"

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior })
  }, [pathname])
  return null
}

function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink-300">404</p>
      <h1 className="mt-2 font-display text-4xl">Esta página no existe</h1>
      <p className="mt-2 max-w-md text-sm text-ink-500">
        Puede que el enlace sea antiguo o que el recurso se haya eliminado.
      </p>
      <Link to="/panel" className="btn-primary mt-5 text-sm no-underline">
        Volver al panel
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ScrollToTop />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/acceder" element={<Auth />} />
          <Route
            element={
              <RequireAuth>
                <Shell />
              </RequireAuth>
            }
          >
            <Route path="/panel" element={<Dashboard />} />
            <Route path="/empresas" element={<Companies />} />
            <Route path="/empresas/:ticker" element={<CompanyDetail />} />
            <Route path="/investigacion" element={<Research />} />
            <Route path="/investigacion/:id" element={<ResearchDetail />} />
            <Route path="/informes" element={<Reports />} />
            <Route path="/informes/:id" element={<ReportDetail />} />
            <Route path="/cartera" element={<Portfolio />} />
            <Route path="/ajustes" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
