import { X509Certificate } from "node:crypto";
import * as tls from "node:tls";

// Temporary eMudhra containment while Vercel rolls out Node 24.22.1.
// These are the two roots removed by certifi 2026.10.19 (DER SHA-256).
// Remove this workaround only after the hosted runtime rejects both incident
// test chains. Never disable TLS validation to work around provider failures.
const DISTRUSTED_ROOTS = new Set([
  "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4", // AAA Certificate Services
  "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b", // emSign ECC Root CA - G3
]);

// @types/node 20 predates these supported Node 22.19+/24.5+ APIs.
type TrustStoreApi = typeof tls & {
  getCACertificates(type: "default"): string[];
  setDefaultCACertificates(certificates: string[]): void;
};

export function excludeCompromisedRoots(certificates: string[]): string[] {
  return certificates.filter((pem) => {
    const fingerprint = new X509Certificate(pem).fingerprint256.replaceAll(":", "").toLowerCase();
    return !DISTRUSTED_ROOTS.has(fingerprint);
  });
}

export function configureTrustedCertificates(): void {
  const trustStore = tls as TrustStoreApi;
  if (typeof trustStore.getCACertificates !== "function" ||
      typeof trustStore.setDefaultCACertificates !== "function") {
    throw new Error("Certificate protection requires Node 22.19+ or 24.5+");
  }
  const certificates = excludeCompromisedRoots(trustStore.getCACertificates("default"));
  if (certificates.length === 0) throw new Error("No trusted CA certificates available");
  // Called at server initialization, before application network I/O.
  // This affects Node HTTPS/fetch, not browser or Edge runtime trust stores.
  trustStore.setDefaultCACertificates(certificates);
}
