export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { configureTrustedCertificates } = await import("./lib/security/trusted-certificates");
    configureTrustedCertificates();
  }
}
