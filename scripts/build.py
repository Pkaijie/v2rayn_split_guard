"""Build and verify a self-contained Windows x64 single-file application."""
from pathlib import Path
import hashlib
import json
import os
import sys
import struct
import zipfile
import PyInstaller.__main__
from PyInstaller.archive.readers import CArchiveReader
import runpy

root=Path(__file__).resolve().parent.parent


def main():
    os.chdir(root)
    sys.path.insert(0,str(root))
    from guard.common import VERSION
    if os.name!='nt' or struct.calcsize('P')!=8 or Path(sys.prefix).name.lower()!='tools':
        raise RuntimeError('请在 Windows 64 位 Conda Tools 环境中构建')
    tools=Path(sys.prefix)
    windows=Path(os.environ['SystemRoot'])
    os.environ['PATH']=os.pathsep.join(str(p) for p in (
        tools,tools/'Library/bin',tools/'Scripts',windows/'System32',windows))
    for key in ('PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY'):
        os.environ.pop(key,None)
    runpy.run_path(str(root/'scripts/make_icon.py'), run_name='__main__')
    runpy.run_path(str(root/'scripts/gather_notices.py'))['collect']()
    build=root/'build';build.mkdir(exist_ok=True)
    spec=build/'portable.spec'
    spec.write_text((root/'scripts/portable.spec.in').read_text(encoding='utf-8'),encoding='utf-8')
    version=tuple(int(n) for n in VERSION.split('.'))+(0,)
    (build/'windows-version.txt').write_text(
        f"""VSVersionInfo(ffi=FixedFileInfo(filevers={version!r}, prodvers={version!r},
mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
kids=[StringFileInfo([StringTable('040904b0', [
StringStruct('FileDescription', 'v2rayN 分流助手'),
StringStruct('FileVersion', '{VERSION}'), StringStruct('ProductVersion', '{VERSION}'),
StringStruct('ProductName', 'v2rayN 分流助手'),
StringStruct('OriginalFilename', 'V2rayNSplitGuard.exe')])]),
VarFileInfo([VarStruct('Translation', [1033, 1200])])])""",encoding='utf-8')
    PyInstaller.__main__.run(['--noconfirm','--clean','--distpath',str(root/'dist'),
                             '--workpath',str(build/'portable'),str(spec)])
    executable=root/'dist/V2rayNSplitGuard.exe'
    archive=CArchiveReader(str(executable))
    required={'python311.dll','vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','assets/app.ico',
              'pyside6/qt6core.dll','pyside6/qt6gui.dll','pyside6/qt6widgets.dll','pyside6/qt6svg.dll',
              'pyside6/plugins/platforms/qwindows.dll','pyside6/plugins/iconengines/qsvgicon.dll'}
    names={n.replace('\\','/').lower() for n in archive.toc}
    if not required<=names:
        raise RuntimeError('EXE 缺少运行库：'+str(sorted(required-names)))
    if any(n.endswith(('tcl86t.dll','tk86t.dll')) for n in names):
        raise RuntimeError('Qt 程序不应附带 Tcl/Tk 运行库')
    checks=runpy.run_path(str(root/'tests/portable_smoke.py'))['run'](executable)
    proof=root/'artifacts/portable-build.json';proof.parent.mkdir(exist_ok=True)
    result=dict(ok=True,version=VERSION,format='onefile',architecture='x64',
                size_bytes=executable.stat().st_size,
                sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                embedded_files=len(names),required_runtime_files_verified=True,checks=checks)
    proof.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    release=root/'release';release.mkdir(exist_ok=True)
    package=release/f'V2rayNSplitGuard-{VERSION}-windows-x64.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as output:
        output.write(executable,executable.name)
        output.write(root/'使用说明.txt','使用说明.txt')
        output.write(root/'README.md','README.md')
        output.write(root/'VALIDATION.md','VALIDATION.md')
        for file in (root/'licenses').rglob('*'):
            if file.is_file():output.write(file,'licenses/'+file.relative_to(root/'licenses').as_posix())
        for file in (root/'build/Qt_licenses').rglob('*'):
            if file.is_file():output.write(file,'licenses/Qt/'+file.relative_to(root/'build/Qt_licenses').as_posix())
        for file in (root/'build/ThirdPartyNotices').rglob('*'):
            if file.is_file():output.write(file,'licenses/ThirdParty/'+file.relative_to(root/'build/ThirdPartyNotices').as_posix())
        manifest=json.loads((root/'licenses/Qt-SOURCES.json').read_text(encoding='utf-8'))
        for source in manifest:
            archive=root/'build/opensource_sources'/source['file']
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=source['sha256']:raise RuntimeError('Qt source hash mismatch')
            output.write(archive,'sources/'+archive.name)
    print(json.dumps(dict(ok=True,exe=str(executable),size_mb=round(result['size_bytes']/1024**2,1),
                          package=str(package),verification=str(proof)),ensure_ascii=False))


if __name__=='__main__':main()
