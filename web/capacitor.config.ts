import type { CapacitorConfig } from "@capacitor/cli"

/**
 * Configuración de Capacitor (fase 9): el wrapper nativo apunta a la build
 * estática de `dist/`. Generar el APK requiere Android SDK y es un paso
 * manual (`npm run cap:android`): este repositorio no declara ningún APK
 * compilado.
 */
const config: CapacitorConfig = {
  appId: "ai.nexo.invest",
  appName: "Nexo Invest AI",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
  android: {
    allowMixedContent: false,
  },
}

export default config
