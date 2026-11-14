"""Verify the final Qt bundle without reading personal configuration or changing routes."""
import ctypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import PySide6
from PySide6 import QtCore,QtGui,QtWidgets,QtSvg
import shiboken6
import psutil
from .common import VERSION,ps_json,run as command
from .qtcheck import smoke
from .elevation import fresh_worker_environment


def run():
    bundled=bool(getattr(sys,'frozen',False));resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
    if bundled:
        for module in (PySide6,QtCore,QtGui,QtWidgets,QtSvg,shiboken6,psutil):
            assert Path(module.__file__).resolve().is_relative_to(resources)
        assert all(Path(p).resolve().is_relative_to(resources) for p in sys.path)
    ui=smoke(real_tray=True)
    if bundled:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];kernel.GetModuleHandleW.restype=ctypes.c_void_p
        kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
        for name in ('python311.dll','Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','Qt6Svg.dll','vcruntime140.dll'):
            module=kernel.GetModuleHandleW(name);buffer=ctypes.create_unicode_buffer(32768)
            assert module and kernel.GetModuleFileNameW(module,buffer,len(buffer))
            assert Path(buffer.value).resolve().is_relative_to(resources),name+' loaded outside the bundle'
        with tempfile.TemporaryDirectory(prefix='split-guard-child-') as tmp:
            proof=Path(tmp)/'child.json'
            with fresh_worker_environment():env=dict(os.environ)
            child=subprocess.run([sys.executable,'--ui-self-test','--output',str(proof)],env=env,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
            assert child.returncode==0 and json.loads(proof.read_text(encoding='utf-8'))['ok']
    system=ps_json('@{powershell=$PSVersionTable.PSVersion.Major;nettcpip=[bool](Get-Module -ListAvailable NetTCPIP)} | ConvertTo-Json -Compress')
    assert system['nettcpip'] and 'curl' in command(['curl.exe','--version'],10).lower()
    return dict(ok=True,version=VERSION,frozen=bundled,bits=struct.calcsize('P')*8,python=sys.version.split()[0],
        ui='PySide6 / Qt Widgets',qt=QtCore.qVersion(),bundled_imports_only=bundled,
        runtime_dlls_bundled=bundled,independent_child_verified=bundled,full_window=True,real_tray=True,
        ui_checks=ui['passed'],system_tools=system,network_writes=0)
