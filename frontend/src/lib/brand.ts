// Brand shown in the panel. Build-time values (VITE_BRAND_*; defaults in
// vite.config.ts), so a second brand built from the same code
// (docker-compose.brand2.yml) never shows Wunderkind.
const name = import.meta.env.VITE_BRAND_NAME

export const BRAND = {
  name,
  appName: import.meta.env.VITE_BRAND_APP_NAME,
  initial: name.trim().charAt(0).toUpperCase(),
}
