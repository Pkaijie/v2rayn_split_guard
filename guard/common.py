from __future__ import annotations

import base64
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import threading
import time

VERSION = '3.0.1'
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'V2rayNSplitGuard'
DEFAULTS = dict(runtime='', gui='',
                wlan='WLAN', company='PPPoE', interval=15, cooldown=120,
                manual=False, host='', port=443, protocol='手动', transport='UDP',
                tag='', gateway='', gateway6='', auto_proxy=False, close_action='ask')


def timestamp():
    return time.strftime('%Y-%m-%d %H:%M:%S %z')


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def setup_log():
    DATA.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger('guard')
    if not log.handlers:
        h = RotatingFileHandler(DATA / 'diagnostics.log', maxBytes=1024*1024,
                                backupCount=3, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def is_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == 'nt' else False


def run(args, timeout=25, stop=None):
    """No shell; bounded, cancellable subprocess with hidden Windows console."""
    check_cancelled(stop)
    args = list(args)
    if os.name == 'nt' and args[0] in {'curl.exe', 'netsh.exe', 'powershell.exe'}:
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
            raise OSError('无法定位 Windows 系统工具目录')
        system = Path(buffer.value)
        args[0] = str(system / ('WindowsPowerShell/v1.0/powershell.exe' if args[0]=='powershell.exe' else args[0]))
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    end = time.monotonic() + timeout
    while True:
        try:
            out, err = p.communicate(timeout=.2)
            break
        except subprocess.TimeoutExpired:
            if (stop and stop.is_set()) or time.monotonic() > end:
                p.kill()
                p.communicate()
                check_cancelled(stop)
                raise TimeoutError('任务已取消或超过时间限制')
    def decode(b):
        try:
            return b.decode('utf-8-sig')
        except UnicodeDecodeError:
            return b.decode('mbcs', errors='replace')
    if p.returncode:
        raise RuntimeError((decode(err) or decode(out) or f'退出码 {p.returncode}')[:1500].strip())
    return decode(out).strip()


class OperationCancelled(RuntimeError):pass


def check_cancelled(stop):
    if stop is not None and stop.is_set():raise OperationCancelled('操作已取消，未执行路由变更')


def stage(name,work,stop=None,progress=None):
    check_cancelled(stop)
    if progress:progress(name)
    started=time.monotonic()
    try:
        result=work();check_cancelled(stop);return result
    finally:logging.getLogger('guard').info('阶段=%s 耗时=%.3fs',name,time.monotonic()-started)


def ps(script, timeout=25, stop=None):
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
    encoded = base64.b64encode((prefix + script).encode('utf-16le')).decode('ascii')
    return run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                '-EncodedCommand', encoded], timeout, stop)


def ps_json(script, timeout=25, stop=None):
    raw = ps(script, timeout, stop)
    return json.loads(raw) if raw else None


def quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def array(x):
    return [] if x is None else x if isinstance(x, list) else [x]
