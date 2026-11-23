"""Read-only, bounded runtime-config discovery. Never return raw process arguments."""
from pathlib import Path
import re
import time

import psutil
from .network import local_proxy_listeners
from .nodes import RUNTIME_SUFFIXES, document_profile, load_runtime_document
from .standalone import CORE_LABELS, brook_profile, is_brook

CORES = {'xray.exe', 'v2ray.exe', 'sing-box.exe', 'sing-box-client.exe', 'sing_box.exe'}
CLASH_CORES = {'clash.exe', 'clash-meta.exe', 'clash.meta.exe', 'mihomo.exe', 'verge-mihomo.exe',
               'clash-win64.exe', 'clash-win32.exe', 'clash-windows.exe', 'mihomo-party-core.exe'}
CLASH_RELEASE = re.compile(r'(?:mihomo|clash(?:-meta)?)-windows-(?:amd64|arm64|386)(?:-[a-z0-9._-]+)?\.exe')
CONFIG_FLAGS = {'-c', '-config', '--config'}
DIRECTORY_FLAGS = {'-D', '--directory'}
MERGE_FLAGS = {'-C', '--config-directory', '-confdir', '--confdir'}
STANDALONE_CORES = {
    'hysteria.exe': 'hysteria2', 'hysteria2.exe': 'hysteria2',
    'naive.exe': 'naiveproxy', 'naiveproxy.exe': 'naiveproxy',
    'tuic.exe': 'tuic', 'tuic-client.exe': 'tuic',
    'juicity.exe': 'juicity', 'juicity-client.exe': 'juicity',
    'overtls.exe': 'overtls', 'overtls-bin.exe': 'overtls',
    'shadowquic.exe': 'shadowquic',
}
HYSTERIA_RELEASE = re.compile(r'hysteria(?:2)?-windows-(?:amd64|arm64|386)(?:-[a-z0-9._-]+)?\.exe')
DEFAULT_CONFIGS = {'hysteria2': ('config.yaml', 'config.yml', 'config.json'),
                   'naiveproxy': ('config.json',)}


def config_arguments(arguments, *, clash=False):
    """psutil supplies an argv list; do not split it or expose other switches."""
    paths, directory, merged = [], '', False
    config_flags = {'-f', '--f'} if clash else CONFIG_FLAGS
    directory_flags = {'-d', '--d'} if clash else DIRECTORY_FLAGS
    args = iter(arguments[1:])
    for token in args:
        flag, separator, value = token.partition('=')
        if clash and flag in {'-config', '--config'}:
            # Mihomo interprets this as inline Base64 data, never as a file path.
            return [], '', True
        if not clash and flag in MERGE_FLAGS:
            merged = True
        if flag not in config_flags | directory_flags:
            continue
        value = value if separator else next(args, '')
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if flag in directory_flags:
            directory = value
        elif value and len(paths) < 8:
            paths.append(value)
    return paths, directory, merged or len(paths) > 1


def runtime_metadata(path):
    """Return only the format and declared SOCKS ports, never config contents."""
    try:
        data = load_runtime_document(path)
        profile = document_profile(data)
    except (OSError, ValueError):
        return None
    if profile.family == 'outbounds' and not any(isinstance(o, dict) and ('type' in o or 'protocol' in o)
                                                for o in data['outbounds']):
        return None
    return profile.family, profile.socks_ports


def runtime_file(path):
    return runtime_metadata(path) is not None


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

    def add(path, rank, source, pid, confirmed, *, metadata=None, expected='', associate=False, ambiguous=False):
        if path is None or len(candidates) >= 64 or stopped():
            return
        metadata = metadata or runtime_metadata(path)
        if metadata is None or stopped():
            return
        family, ports = metadata
        if expected and family != expected and (family, expected) != ('hysteria', 'hysteria2'):
            return
        if associate and any(listeners.get(port, {}).get('pid') == pid for port in ports):
            rank, source = 0, '代理监听进程参数'
            confirmed = not ambiguous
        if ambiguous:
            source += '（多文件/目录配置，需确认）'
        if family == 'clash':
            source = 'Clash / Mihomo · ' + source
        elif family in CORE_LABELS:
            source = CORE_LABELS[family] + ' · ' + source
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
            listeners = {} if stopped() else local_proxy_listeners()
        except (psutil.Error, OSError):
            listeners = {}
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
            clash = name in CLASH_CORES or CLASH_RELEASE.fullmatch(name) is not None
            standalone = STANDALONE_CORES.get(name, '')
            if HYSTERIA_RELEASE.fullmatch(name):
                standalone = 'hysteria2'
            brook = is_brook(name)
            if name not in CORES and not (clash or brook or standalone or pid in guis):
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
                arguments = process.cmdline()
                linked = owned_by_v2rayn(pid)
                rank = 1 if linked else 2
                if brook:
                    profile = brook_profile(arguments)
                    if profile:
                        add(f'@brook:{pid}', rank, '客户端进程', pid, linked,
                            metadata=(profile.family, profile.socks_ports), associate=True)
                    continue
                if standalone == 'overtls' and not overtls_client(arguments):
                    continue
                if standalone == 'hysteria2' and any(arg in ('server', 's') for arg in arguments[1:]):
                    continue
                if standalone == 'naiveproxy' and any(arg.partition('=')[0] in (
                        '--proxy', '--listen', '--host-resolver-rules') for arg in arguments[1:]):
                    notes.add('NaiveProxy 使用命令行覆盖配置，请手动核对实际节点和监听端口。')
                    continue
                paths, directory, merged = config_arguments(arguments, clash=clash)
                if not paths and (standalone == 'naiveproxy' or name == 'v2ray.exe'):
                    positional = arguments[1].strip('"') if len(arguments) > 1 else ''
                    if not positional.startswith('-') and Path(positional).suffix.lower() in RUNTIME_SUFFIXES:
                        paths = [positional]
                try:
                    cwd = process.cwd()
                except (psutil.Error, OSError):
                    cwd = None
                base = _absolute(directory, cwd) if directory else cwd
                source = 'v2rayN 核心进程参数' if linked else '独立核心参数，归属需确认'
                if merged:
                    notes.add('发现内联、多文件或目录配置，不能自动认定单个文件代表完整运行配置。')
                if clash and not paths and not merged:
                    if directory and base:
                        add(_absolute('config.yaml', base), rank, '核心配置目录', pid, linked, associate=True)
                    continue
                if not paths and not merged and standalone in DEFAULT_CONFIGS:
                    for filename in DEFAULT_CONFIGS[standalone]:
                        add(_absolute(filename, cwd), rank, '工作目录候选', pid, False,
                            expected=standalone, associate=True, ambiguous=len(DEFAULT_CONFIGS[standalone]) > 1)
                for value in paths:
                    path = _absolute(value, cwd if clash else base) if value != '-' else None
                    if path is None:
                        notes.add('部分相对配置路径无法解析，请手动确认。')
                    add(path, rank, source, pid, linked and not merged, expected=standalone,
                        associate=True, ambiguous=merged)
            except (psutil.Error, OSError):
                notes.add('部分核心进程信息不可读取，请手动选择或确认文件。')
        if stopped() and not (stop is not None and stop.is_set()):
            notes.add('检测已到时间限制，仅列出已找到的候选。')
            # Incomplete discovery must not imply there was only one choice.
            for item in candidates.values():item['confirmed'] = False
        if not candidates:
            notes.add('未找到可读取的运行配置。请先启动代理客户端，再重试或手动选择文件。')
        return result()
    except (psutil.Error, OSError):
        notes.add('无法完成进程检测，请手动选择运行配置。')
        for item in candidates.values():item['confirmed'] = False
        return result()


def overtls_client(arguments):
    for index, token in enumerate(arguments[1:], 1):
        flag, eq, value = token.partition('=')
        if flag in ('-r', '--role'):
            role = value if eq else arguments[index + 1] if index + 1 < len(arguments) else ''
            return role == 'client'
    return False
