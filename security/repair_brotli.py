"""Rebuild Pillow's private Brotli pair from checksum-pinned patched source."""
import ctypes
import hashlib
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

SOURCES = {
    0x1001000: ('1.1.1', '1a84dfaa740994d19254bf78aa7d74a4a8040d1638f3d5f2cdecb188fd520da8'),
    0x1002000: ('1.2.1', '98d35d11a78dc453aebb7d10c3748f3f73ff78c8267c0dc697b8631f67bf7e8f'),
}


def version(path):
    lib = ctypes.CDLL(str(path))
    lib.BrotliDecoderVersion.restype = ctypes.c_uint32
    return lib.BrotliDecoderVersion()


def main():
    decoders = list(pathlib.Path('/usr/local/lib').glob('python*/site-packages/pillow.libs/libbrotlidec*.so*'))
    if len(decoders) != 1:
        raise RuntimeError(f'Expected one Pillow Brotli decoder, found {len(decoders)}')
    decoder = decoders[0]
    commons = list(decoder.parent.glob('libbrotlicommon*.so*'))
    if len(commons) != 1:
        raise RuntimeError('Expected one private common library')
    common = commons[0]
    ctypes.CDLL(str(common), mode=ctypes.RTLD_GLOBAL)
    original = version(decoder)
    if original not in SOURCES:
        raise RuntimeError(f'Unreviewed Pillow Brotli version: {original:#x}')
    patched, expected_sha = SOURCES[original]
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        archive = root / 'source.tar.gz'
        with urllib.request.urlopen(f'https://codeload.github.com/google/brotli/tar.gz/refs/tags/v{patched}', timeout=60) as response:
            archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha:
            raise RuntimeError('Brotli source checksum mismatch')
        with tarfile.open(archive) as bundle:
            bundle.extractall(root, filter='data')
        source = root / f'brotli-{patched}'
        flags = ['gcc', '-shared', '-O2', '-fPIC', '-fvisibility=hidden', '-DBROTLI_SHARED_COMPILATION', '-I', str(source / 'c/include')]
        subprocess.run(flags + ['-DBROTLICOMMON_SHARED_COMPILATION'] + [str(p) for p in (source / 'c/common').glob('*.c')] + ['-Wl,-soname,' + common.name, '-o', str(root / common.name)], check=True)
        subprocess.run(flags + ['-DBROTLIDEC_SHARED_COMPILATION'] + [str(p) for p in (source / 'c/dec').glob('*.c')] + ['-L', str(root), '-l:' + common.name, '-Wl,-soname,' + decoder.name, '-Wl,-rpath,$ORIGIN', '-o', str(root / decoder.name)], check=True)
        # A separate process is essential: this process already loaded the old pair.
        subprocess.run(['python', '-I', '-c', 'import ctypes,sys; l=ctypes.CDLL(sys.argv[1]); l.BrotliDecoderVersion.restype=ctypes.c_uint32; assert l.BrotliDecoderVersion()==int(sys.argv[2])', str(root / decoder.name), str(original + 1)], check=True)
        # Atomic replacement avoids modifying a library mapped by this process.
        for path in [common, decoder]:
            replacement = path.with_name(path.name + '.patched')
            shutil.copyfile(root / path.name, replacement)
            replacement.replace(path)
    print(f'Pillow private Brotli repaired to {patched}; original SONAMEs preserved')


if __name__ == '__main__':
    main()
