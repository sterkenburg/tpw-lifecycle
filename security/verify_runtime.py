"""Offline build gate: inspect actual libraries and both trust stores."""
import ctypes
import glob
import ssl
import subprocess
import certifi

assert tuple(map(int, certifi.__version__.split('.'))) >= (2026, 10, 19)
for cafile in [certifi.where(), '/etc/ssl/certs/ca-certificates.crt']:
    roots = ssl.create_default_context(cafile=cafile).get_ca_certs()
    subjects = {value for root in roots for group in root['subject'] for key, value in group if key == 'commonName'}
    assert not subjects.intersection({'AAA Certificate Services', 'emSign ECC Root CA - G3'})
package = subprocess.run(['dpkg-query', '-W', '-f=${Version}', 'libbrotli1'], capture_output=True, text=True)
if package.returncode == 0:
    subprocess.run(['dpkg', '--compare-versions', package.stdout, 'ge', '1.1.0-2+deb13u1'], check=True)
paths = glob.glob('/usr/local/lib/python*/site-packages/pillow.libs/libbrotlidec*.so*')
assert len(paths) == 1
for path in paths:
    lib = ctypes.CDLL(path)
    lib.BrotliDecoderVersion.restype = ctypes.c_uint32
    assert lib.BrotliDecoderVersion() in (0x1001001, 0x1002001)
    # RFC7932 hello fixture, plus malformed input rejection.
    decode = lib.BrotliDecoderDecompress
    decode.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    for encoded, valid in [(bytes.fromhex('0b028068656c6c6f03'), True), (b'\xff' * 20, False)]:
        output = ctypes.create_string_buffer(64)
        size = ctypes.c_size_t(64)
        result = decode(len(encoded), encoded, ctypes.byref(size), output)
        assert (result == 1) == valid
        if valid:
            assert output.raw[:size.value] == b'hello'
from PIL import Image, ImageFont
import io
for fmt in ('PNG', 'JPEG', 'WEBP'):
    stream = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(stream, format=fmt)
    stream.seek(0)
    assert Image.open(stream).size == (4, 4)
print('Patched private/system Brotli, image controls and certificate stores verified')
