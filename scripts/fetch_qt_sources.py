"""Developer-only: cache exact Qt/PySide sources and their original license texts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from guard.common import run

VERSION='6.11.3'
BASE='https://download.qt.io/official_releases/'
SOURCES={
    'qtbase':BASE+f'qt/6.11/{VERSION}/submodules/qtbase-everywhere-src-{VERSION}.tar.xz',
    'qtsvg':BASE+f'qt/6.11/{VERSION}/submodules/qtsvg-everywhere-src-{VERSION}.tar.xz',
    'pyside-setup':BASE+f'QtForPython/pyside6/PySide6-{VERSION}-src/pyside-setup-everywhere-src-{VERSION}.tar.xz',
}


def fetch(socks=''):
    cache=ROOT/'build'/'opensource_sources';cache.mkdir(parents=True,exist_ok=True)
    records=[]
    for component,url in SOURCES.items():
        target=cache/url.rsplit('/',1)[1]
        if not target.is_file():
            temporary=target.with_suffix(target.suffix+'.tmp')
            args=['curl.exe','-q','--location','--fail','--silent','--show-error','--connect-timeout','10','--max-time','300']
            if socks:args+=['--socks5-hostname',socks]
            print('Downloading',component,flush=True)
            run(args+['--output',str(temporary),url],320)
            temporary.replace(target)
        assert tarfile.is_tarfile(target), 'Invalid source archive: '+component
        print('Collecting license texts',component,flush=True)
        count=0
        with tarfile.open(target,'r:xz') as archive:
            for item in archive:
                name=Path(item.name)
                if not item.isfile() or item.size>1024*1024 or not re.search(r'license|licence|copying|copyright',name.name,re.I):continue
                relative=Path(*name.parts[1:])
                destination=(ROOT/'build'/'Qt_licenses'/component/relative).resolve()
                assert destination.is_relative_to((ROOT/'build'/'Qt_licenses').resolve())
                source=archive.extractfile(item)
                if source is not None:
                    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(source.read());count+=1
        records.append(dict(component=component,version=VERSION,file=target.name,url=url,
                            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),license_files=count))
    (ROOT/'licenses'/'Qt-SOURCES.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--socks',default='');args=parser.parse_args()
    print(json.dumps(fetch(args.socks),ensure_ascii=False))
