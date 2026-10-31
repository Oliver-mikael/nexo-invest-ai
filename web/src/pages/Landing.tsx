import { Link } from "react-router-dom"
import { useAuth } from "../lib/auth"

const FEATURES = [
  {
    title: "Motor verificable",
    body: "DCF, escenarios y sensibilidad calculados en el servidor con cifras de SEC EDGAR, unidad, periodo y SHA-256 del documento a la vista.",
    tag: "Cálculo",
  },
  {
    title: "IA auditada",
    body: "Cinco roles —investigador, analista, auditor, contrario y coordinador— sobre un expediente cerrado. Cada cifra generada se contrasta y lo que no tiene respaldo se marca.",
    tag: "Orquestación",
  },
  {
    title: "Cartera simulada",
    body: "Registra compras y ventas ficticias, sigue el coste medio y compara la tesis con el resultado. Sin bróker, sin dinero real.",
    tag: "Seguimiento",
  },
  {
    title: "Instalable y responsive",
    body: "Funciona en escritorio, tableta y móvil. Se instala como aplicación con service worker propio; los datos financieros nunca se guardan en caché.",
    tag: "PWA",
  },
]

const STEPS = [
  {
    number: "01",
    title: "Datos primarios",
    body: "La SEC publica los estados financieros. Nexo los descarga, valida identidad contable, unidades y fechas, y registra la huella del documento.",
  },
  {
    number: "02",
    title: "Motor y escenarios",
    body: "Las métricas y la valoración salen del motor determinista: pesimista, base y optimista, con tabla de sensibilidad y supuestos editables.",
  },
  {
    number: "03",
    title: "Investigación y auditoría",
    body: "Los modelos redactan análisis sobre el expediente; el auditor contrasta cifras y fuentes. El informe conserva desacuerdos y limitaciones.",
  },
]

export function Landing() {
  const { user } = useAuth()

  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-2xl tracking-tight">Nexo</span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-300">
            Invest AI
          </span>
        </div>
        <nav className="flex items-center gap-2">
          <a href="#producto" className="hidden px-3 py-2 text-sm text-ink-500 no-underline hover:text-ink-900 sm:inline">
            Producto
          </a>
          <a href="#metodo" className="hidden px-3 py-2 text-sm text-ink-500 no-underline hover:text-ink-900 sm:inline">
            Método
          </a>
          <Link to={user ? "/panel" : "/acceder"} className="btn-dark text-sm no-underline">
            {user ? "Ir al panel" : "Entrar"}
          </Link>
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl gap-10 px-5 pb-16 pt-8 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <div className="animate-rise">
          <span className="chip bg-moss-100 text-moss-600">Investigación financiera trazable</span>
          <h1 className="mt-5 font-display text-[2.6rem] leading-[1.05] tracking-tight text-ink-900 sm:text-6xl">
            Cada cifra tiene un documento detrás.
            <span className="block italic text-moss-600">Cada opinión, una etiqueta.</span>
          </h1>
          <p className="mt-5 max-w-xl text-[15px] leading-relaxed text-ink-500">
            Nexo Invest AI combina un motor de valoración determinista con un orquestador de
            modelos que investiga, se contradice y se audita. Hechos, estimaciones, supuestos e
            interpretaciones de IA van separados en el mismo informe.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link to={user ? "/investigacion" : "/acceder"} className="btn-primary text-sm no-underline">
              {user ? "Nueva investigación" : "Crear cuenta"}
            </Link>
            <a href="#metodo" className="btn-ghost text-sm no-underline">
              Cómo funciona
            </a>
          </div>
          <dl className="mt-9 grid max-w-lg grid-cols-3 gap-4 border-t border-ink-900/10 pt-5">
            {[
              ["5", "roles de IA"],
              ["18", "secciones por informe"],
              ["0", "recomendaciones"],
            ].map(([value, label]) => (
              <div key={label}>
                <dt className="font-display text-3xl text-ink-900">{value}</dt>
                <dd className="text-xs uppercase tracking-[0.08em] text-ink-300">{label}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative animate-rise">
          <div className="absolute -inset-4 rounded-[28px] bg-gradient-to-br from-moss-500/10 via-transparent to-amber-500/10" />
          <div className="surface relative overflow-hidden p-0">
            <div className="flex items-center justify-between border-b border-ink-900/10 bg-ink-900 px-5 py-3 text-paper">
              <span className="font-mono text-xs tracking-wide">AAPL · Valoración base</span>
              <span className="chip bg-white/10 text-[10px] text-paper/80">datos SEC</span>
            </div>
            <div className="space-y-4 p-5">
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["Pesimista", "94,12", "text-ink-500"],
                  ["Base", "118,93", "text-moss-600"],
                  ["Optimista", "151,40", "text-amber-600"],
                ].map(([label, value, color]) => (
                  <div key={label} className="rounded-lg border border-ink-900/10 bg-paper/60 p-3">
                    <p className="text-[10px] uppercase tracking-[0.08em] text-ink-300">{label}</p>
                    <p className={`font-mono text-lg ${color}`}>{value}</p>
                  </div>
                ))}
              </div>
              <div className="rounded-lg border border-ink-900/10">
                <div className="grid grid-cols-4 border-b border-ink-900/10 bg-white/70 px-3 py-2 text-[10px] uppercase tracking-[0.08em] text-ink-300">
                  <span>Descuento</span>
                  <span className="text-right">g 2,0%</span>
                  <span className="text-right">g 2,5%</span>
                  <span className="text-right">g 3,0%</span>
                </div>
                {[
                  ["7,5%", "147,20", "157,84", "170,05"],
                  ["8,5%", "112,44", "118,93", "126,30"],
                  ["9,5%", "88,19", "92,67", "97,71"],
                ].map((row) => (
                  <div
                    key={row[0]}
                    className="grid grid-cols-4 border-b border-ink-900/5 px-3 py-2 font-mono text-xs text-ink-700 last:border-b-0"
                  >
                    {row.map((cell, index) => (
                      <span key={index} className={index === 0 ? "text-ink-500" : "text-right"}>
                        {cell}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-ink-300">
                Tabla ilustrativa del formato de salida. En el producto, cada celda se calcula con
                el FCF observado y los supuestos declarados; las combinaciones imposibles se marcan
                como no calculables.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="producto" className="border-y border-ink-900/10 bg-white/50">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="font-display text-3xl tracking-tight sm:text-4xl">
            Un producto, no un tablero decorativo
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-500">
            Backend con API versionada, base de datos, autenticación, cola de trabajos persistente
            y presupuesto de IA por investigación. La interfaz solo presenta lo que el servidor ha
            calculado.
          </p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {FEATURES.map((feature) => (
              <article key={feature.title} className="surface p-6">
                <span className="chip-muted">{feature.tag}</span>
                <h3 className="mt-3 font-display text-2xl text-ink-900">{feature.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-500">{feature.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="metodo" className="mx-auto max-w-6xl px-5 py-16">
        <h2 className="font-display text-3xl tracking-tight sm:text-4xl">Del 10-K al informe</h2>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {STEPS.map((step) => (
            <div key={step.number} className="border-t border-ink-900/15 pt-4">
              <span className="font-mono text-xs text-moss-600">{step.number}</span>
              <h3 className="mt-2 font-display text-xl">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-500">{step.body}</p>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-start justify-between gap-4 rounded-xl bg-ink-900 px-6 py-8 text-paper sm:flex-row sm:items-center">
          <div>
            <p className="font-display text-2xl">Empieza con una empresa que conozcas.</p>
            <p className="mt-1 text-sm text-paper/60">
              Apple y Microsoft ya están validadas con datos vivos en este repositorio.
            </p>
          </div>
          <Link
            to={user ? "/panel" : "/acceder"}
            className="btn bg-paper text-ink-900 no-underline hover:bg-white"
          >
            {user ? "Abrir el panel" : "Entrar en Nexo"}
          </Link>
        </div>
      </section>

      <footer className="border-t border-ink-900/10 px-5 py-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 text-xs text-ink-300 sm:flex-row sm:items-center sm:justify-between">
          <p>Nexo Invest AI · Motor de investigación reproducible. No es asesoramiento financiero.</p>
          <p>Datos de SEC EDGAR. Sin órdenes reales ni conexión con brókers.</p>
        </div>
      </footer>
    </div>
  )
}
