# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Collect tkinterdnd2: DLL + TCL scripts + hidden imports
dnd_d, dnd_b, dnd_h = collect_all('tkinterdnd2')

# Filter tkinterdnd2 data to Windows x64 only (drop linux/osx/arm64 folders)
dnd_d = [
    (src, dst) for src, dst in dnd_d
    if not any(p in src.lower() for p in ['linux', 'osx', 'win-arm64', 'win-x86'])
]

# Collect ebooklib: plugins sub-package
ebl_d, ebl_b, ebl_h = collect_all('ebooklib')

# Anaconda builds of lxml and Pillow depend on these DLLs which PyInstaller
# cannot resolve automatically — add them explicitly.
_ANACONDA_BIN = r'C:\Users\00dav\anaconda3\Library\bin'
extra_binaries = [
    # Previously added:
    (fr'{_ANACONDA_BIN}\libxml2.dll',      '.'),
    (fr'{_ANACONDA_BIN}\freetype.dll',     '.'),
    (fr'{_ANACONDA_BIN}\tiff.dll',         '.'),
    (fr'{_ANACONDA_BIN}\openjp2.dll',      '.'),
    # Fixes startup crash (pyexpat / xml.parsers.expat):
    (fr'{_ANACONDA_BIN}\libexpat.dll',     '.'),
    # Other stdlib / runtime dependencies:
    (fr'{_ANACONDA_BIN}\LIBBZ2.dll',       '.'),   # _bz2 / bz2
    (fr'{_ANACONDA_BIN}\ffi.dll',          '.'),   # _ctypes / cffi
    # lxml XSLT support (used by ebooklib):
    (fr'{_ANACONDA_BIN}\libxslt.dll',      '.'),
    (fr'{_ANACONDA_BIN}\libexslt.dll',     '.'),
    # Pillow image format support:
    (fr'{_ANACONDA_BIN}\libwebp.dll',      '.'),
    (fr'{_ANACONDA_BIN}\libwebpmux.dll',   '.'),
    (fr'{_ANACONDA_BIN}\libwebpdemux.dll', '.'),
    (fr'{_ANACONDA_BIN}\lcms2.dll',        '.'),
    # Tcl/Tk runtime:
    (fr'{_ANACONDA_BIN}\tcl86t.dll',       '.'),
    (fr'{_ANACONDA_BIN}\tk86t.dll',        '.'),
]

a = Analysis(
    ['converter.py'],
    pathex=[],
    binaries=dnd_b + ebl_b + extra_binaries,
    datas=dnd_d + ebl_d,
    hiddenimports=(
        dnd_h + ebl_h +
        [
            'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL._imagingtk',
            'lxml', 'lxml.etree', 'lxml._elementpath', 'lxml.html',
            'six',
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude large scientific packages that the app does not use
    excludes=[
        'numpy', 'pandas', 'scipy', 'matplotlib', 'IPython',
        'notebook', 'mkl', 'psutil', 'pyyaml', 'yaml',
    ],
    noarchive=False,
)

# Strip MKL and numpy DLLs from collected binaries — they are pulled in
# transitively by Anaconda's Pillow/numpy but are not used by this app.
a.binaries = [
    b for b in a.binaries
    if not any(tok in b[0].lower() for tok in ['mkl', 'numpy', 'libopenblas'])
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PlainTXT-EPUB Converter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PlainTXT-EPUB Converter',
)
