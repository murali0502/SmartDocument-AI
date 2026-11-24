let origin
try {
  origin = new URL(process.env.VITE_SMARTDOC_API_ORIGIN)
} catch {
  throw new Error("Set VITE_SMARTDOC_API_ORIGIN to the replacement backend's HTTPS origin.")
}
if (origin.protocol !== "https:" || origin.origin !== process.env.VITE_SMARTDOC_API_ORIGIN) {
  throw new Error("VITE_SMARTDOC_API_ORIGIN must be an HTTPS origin without a path or credentials.")
}
