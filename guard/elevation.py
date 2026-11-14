from __future__ import annotations
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import uuid
import hashlib
import json
import re
import os
from contextlib import contextmanager
from .common import DATA, is_admin, read_json, save_json


@contextmanager
def fresh_worker_environment():
    # A UAC process may not have the original bootloader as its ancestor.
    # Give a frozen worker its own extracted runtime instead of inheriting the
    # GUI's temporary directory; restore the GUI environment even on cancel.
    if not getattr(sys,'frozen',False):
        yield
        return
    name='PYINSTALLER_RESET_ENVIRONMENT'
    previous=os.environ.get(name)
    os.environ[name]='1'
    try:
        yield
    finally:
        if previous is None:os.environ.pop(name,None)
        else:os.environ[name]=previous


def worker(request_path, result_path, expected_digest):
    request_path,result_path=Path(request_path).resolve(),Path(result_path).resolve()
    jobs=(DATA/'jobs').resolve()
    match=re.fullmatch(r'([0-9a-f]{32})\.request\.json',request_path.name)
    if (not match or request_path.parent!=jobs or result_path.parent!=jobs or
        result_path.name!=match[1]+'.result.json'):
        return
    try:
        raw=request_path.read_bytes()
        if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=expected_digest:
            raise ValueError('提权请求内容已变化，已拒绝执行')
        request = json.loads(raw)
        if not is_admin():
            raise PermissionError('管理员权限不足')
        if request['action']=='routes':
            from .routes import execute
            result = execute(request['plan'],progress=lambda text:save_json(result_path,dict(running=True,stage=text)))
        else:
            raise ValueError('未知操作')
        save_json(result_path,dict(ok=True,result=result))
    except Exception as e:
        save_json(result_path,dict(ok=False,error=str(e)[:2000]))


def elevated_job(request, stop=None,progress=None):
    """UAC only after a GUI click. Wait without blocking the GUI thread."""
    jobs = DATA/'jobs'
    jobs.mkdir(parents=True,exist_ok=True)
    ident = uuid.uuid4().hex
    req, res = jobs/f'{ident}.request.json',jobs/f'{ident}.result.json'
    save_json(req,request)
    digest=hashlib.sha256(req.read_bytes()).hexdigest()
    if getattr(sys,'frozen',False):
        executable, args = sys.executable,['--worker',str(req),str(res),digest]
    else:
        executable = str(Path(sys.executable).with_name('pythonw.exe'))
        args = [str(Path(__file__).resolve().parent.parent/'app.py'),'--worker',str(req),str(res),digest]
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('fMask',ctypes.c_ulong),('hwnd',wintypes.HWND),
                  ('lpVerb',wintypes.LPCWSTR),('lpFile',wintypes.LPCWSTR),('lpParameters',wintypes.LPCWSTR),
                  ('lpDirectory',wintypes.LPCWSTR),('nShow',ctypes.c_int),('hInstApp',wintypes.HINSTANCE),
                  ('lpIDList',ctypes.c_void_p),('lpClass',wintypes.LPCWSTR),('hkeyClass',wintypes.HKEY),
                  ('dwHotKey',wintypes.DWORD),('hIcon',wintypes.HANDLE),('hProcess',wintypes.HANDLE)]
    info = SHELLEXECUTEINFO()
    info.cbSize,info.fMask,info.lpVerb,info.lpFile = ctypes.sizeof(info),0x40|0x400,'runas',executable
    info.lpParameters,info.nShow = subprocess.list2cmdline(args),0
    shell = ctypes.windll.shell32.ShellExecuteExW
    shell.argtypes, shell.restype = [ctypes.POINTER(SHELLEXECUTEINFO)],wintypes.BOOL
    kernel = ctypes.windll.kernel32
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    try:
        if progress:progress('等待管理员授权；取消授权不会执行变更')
        with fresh_worker_environment():
            if not shell(ctypes.byref(info)):
                raise PermissionError('管理员授权被取消或无法启动提升权限任务；未执行操作')
        last=''
        while kernel.WaitForSingleObject(info.hProcess,200)==258:
            # Route transactions must finish/rollback; never force kill mid-write.
            try:pending=read_json(res,{}) or {}
            except (OSError,ValueError):pending={}
            text=pending.get('stage','管理员任务运行中，请等待完成或回滚')
            if progress and text!=last:progress(text);last=text
        reply = read_json(res)
        if not reply or reply.get('running'):
            raise RuntimeError('管理员任务未返回结果，请查看日志和路由备份')
        if not reply['ok']:
            raise RuntimeError(reply['error'])
        return reply['result']
    finally:
        if info.hProcess:
            kernel.CloseHandle(info.hProcess)
        for path in (req,res):
            path.unlink(missing_ok=True)
