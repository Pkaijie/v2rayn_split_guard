"""Generate dependency notices into the ignored build folder."""
from importlib.metadata import distribution
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent


def collect():
    target=ROOT/'build'/'ThirdPartyNotices';target.mkdir(parents=True,exist_ok=True)
    for name in ('psutil','PyInstaller'):
        dist=distribution(name)
        for item in dist.files:
            if 'license' not in str(item).lower() and item.name!='COPYING.txt':continue
            source=Path(dist.locate_file(item))
            if source.is_file() and source.stat().st_size<200000:
                (target/(name+'-'+source.name)).write_bytes(source.read_bytes())
    candidates=[Path(sys.prefix)/name for name in ('LICENSE.txt','LICENSE_PYTHON.txt','LICENSE')]
    source=next((p for p in candidates if p.is_file()),None)
    if source is not None:(target/'Python-LICENSE.txt').write_bytes(source.read_bytes())
    elif not (target/'Python-LICENSE.txt').is_file():raise RuntimeError('缺少 Python 原始许可文本')
    return target


if __name__=='__main__':print(collect())
