const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const tls = require('node:tls');
const { X509Certificate } = require('node:crypto');
(async () => {
  const { excludeCompromisedRoots, configureTrustedCertificates } = await import('../src/lib/security/trusted-certificates.ts');
  const blocked = ['blocked-0.pem', 'blocked-1.pem'].map(n => fs.readFileSync(path.join(__dirname, 'fixtures/certificates', n), 'utf8'));
  const trusted = tls.rootCertificates.filter(pem => !/AAA Certificate Services|emSign ECC Root CA - G3/.test(new X509Certificate(pem).subject));
  assert.deepEqual(excludeCompromisedRoots([...trusted, ...blocked, ...blocked]), trusted);
  assert.deepEqual(excludeCompromisedRoots(trusted), trusted);
  assert.deepEqual(excludeCompromisedRoots(blocked), []);
  assert.throws(() => excludeCompromisedRoots(['invalid certificate']));
  configureTrustedCertificates();
  assert.ok(tls.getCACertificates('default').length > 100);
  assert.deepEqual(excludeCompromisedRoots(tls.getCACertificates('default')), tls.getCACertificates('default'));
  console.log('PASS: exact root exclusion, extras/duplicates, preservation, idempotence, malformed fail closed, applied default store');
})().catch(e => { console.error(e); process.exitCode = 1; });
