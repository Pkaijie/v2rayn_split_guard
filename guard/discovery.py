"""Read-only, bounded runtime-config discovery. Never return raw process arguments."""
import json
from pathlib import Path
import time

import psutil
from .network import proxy_listener

CORES = {'xray.exe', 'v2ray.exe', 'sing-box.exe', 'sing_box.exe',
         'hysteria.exe', 'hysteria2.exe', 'tuic.exe', 'naive.exe'}
CONFIG_FLAGS = {'-c', '-config', '--config'}
DIRECTORY_FLAGS = {'-D', '--directory'}
MERGE_FLAGS = {'-C', '--config-directory', '-confdir', '--confdir'}
MAX_BYTES = 8 * 1024 * 1024


def config_arguments(arguments):
    """psutil supplies an argv list; do not split it or expose other switches."""
    paths, directory, merged = [], '', False
    args = iter(arguments[1:])
    for token in args:
        flag, separator, value = token.partition('=')
        if flag in MERGE_FLAGS:
            merged = True
        if flag not in CONFIG_FLAGS | DIRECTORY_FLAGS:
            continue
        value = value if separator else next(args, '')
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if flag in DIRECTORY_FLAGS:
            directory = value
        elif value and len(paths) < 8:
            paths.append(value)
    return paths, directory, merged or len(paths) > 1


def runtime_file(path):
    """Check only the runtime shape, without propagating endpoint/credential data."""
    try:
        with Path(path).open('rb') as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return False
        data = json.loads(raw)
        return (isinstance(data, dict) and isinstance(data.get('outbounds'), list)
                and any(isinstance(o, dict) and ('type' in o or 'protocol' in o)
                        for o in data['outbounds']))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return False


def _absolute(value, base):
    if not value:
        return None
    path = Path(value)
    # Discovery must not probe UNC shares or device paths from process arguments.
    if str(path).startswith('\\\\'):
        return None
    if not path.is_absolute():
        if not base:
            return None
        path = Path(base) / path
    if not path.is_absolute() or str(path).startswith('\\\\'):
        return None
    try:
        resolved = path.resolve()
        return None if str(resolved).startswith('\\\\') else resolved
    except (OSError, ValueError):
        return None


def discover_runtime(stop=None, *, timeout=6):
    deadline = time.monotonic() + timeout
    candidates, notes = {}, set()

    def stopped():
        return (stop is not None and stop.is_set()) or time.monotonic() >= deadline

    def result():
        items = sorted(candidates.values(), key=lambda c: (c['rank'], c['path'].casefold()))
        best = [c for c in items if c['rank'] == items[0]['rank']] if items else []
        automatic = best[0]['path'] if len(best) == 1 and best[0]['confirmed'] else ''
        return dict(candidates=items, automatic=automatic, notes=sorted(notes),
                    cancelled=bool(stop is not None and stop.is_set()))

    def add(path, rank, source, pid, confirmed):
        if path is None or len(candidates) >= 64 or stopped() or not runtime_file(path):
            return
        key = str(path).casefold()
        item = dict(path=str(path), rank=rank, source=source, pid=pid, confirmed=confirmed)
        if key not in candidates or rank < candidates[key]['rank']:
            candidates[key] = item

    try:
        processes = {}
        for process in psutil.process_iter(['name', 'ppid']):
            if stopped():break
            processes[process.pid] = (process, (process.info.get('name') or '').lower(),
                                      process.info.get('ppid'))
        guis = {pid for pid, (_, name, _) in processes.items() if name == 'v2rayn.exe'}
        try:
            listener = None if stopped() else proxy_listener()
            listener_pid = listener.get('pid') if listener else None
        except (psutil.Error, OSError):
            listener_pid = None
            notes.add('无法关联本地代理监听进程，候选可能需要手动确认。')

        def owned_by_v2rayn(pid):
            seen = set()
            for _ in range(8):
                if pid in guis:return True
                if pid in seen or pid not in processes:return False
                seen.add(pid);pid = processes[pid][2]
            return False

        for pid, (process, name, _) in processes.items():
            if stopped():break
            if name not in CORES and pid not in guis:
                continue
            if pid in guis:
                try:
                    exe = _absolute(process.exe(), None)
                    if exe:
                        add(exe.parent/'binConfigs'/'config.json', 3,
                            'v2rayN 目录候选，尚未确认核心加载', pid, False)
                except (psutil.Error, OSError):
                    notes.add('部分 v2rayN 进程路径不可读取，请手动选择或确认文件。')
                continue
            try:
                paths, directory, merged = config_arguments(process.cmdline())
                try:
                    cwd = process.cwd()
                except (psutil.Error, OSError):
                    cwd = None
                base = _absolute(directory, cwd) if directory else cwd
                linked = owned_by_v2rayn(pid)
                rank = 0 if pid == listener_pid else 1 if linked else 2
                source = ('代理监听进程参数' if rank == 0 else 'v2rayN 核心进程参数' if linked
                          else '独立核心参数，归属需确认')
                if merged:
                    source += '（多文件/目录配置，需确认）'
                    notes.add('发现多文件或目录配置，不能自动认定单个文件代表完整运行配置。')
                for value in paths:
                    path = _absolute(value, base)
                    if path is None:
                        notes.add('部分相对配置路径无法解析，请手动确认。')
                    add(path, rank, source, pid, rank < 2 and not merged)
            except (psutil.Error, OSError):
                notes.add('部分核心进程信息不可读取，请手动选择或确认文件。')
        if stopped() and not (stop is not None and stop.is_set()):
            notes.add('检测已到时间限制，仅列出已找到的候选。')
            # Incomplete discovery must not imply there was only one choice.
            for item in candidates.values():item['confirmed'] = False
        if not candidates:
            notes.add('未找到可读取的运行配置。请先启动 v2rayN 和代理核心，再重试或手动选择文件。')
        return result()
    except (psutil.Error, OSError):
        notes.add('无法完成进程检测，请手动选择运行配置。')
        for item in candidates.values():item['confirmed'] = False
        return result()
