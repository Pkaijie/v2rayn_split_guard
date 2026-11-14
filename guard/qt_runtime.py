"""Optional user-supplied replacement of LGPL Qt/PySide runtime libraries.

No override is read from app settings. Normal launches always use bundled Qt.
"""
import os
from pathlib import Path
import sys

ENV='V2RAYN_SPLIT_GUARD_QT_RUNTIME'


def apply_runtime_override(argv):
    value=os.environ.get(ENV,'')
    if '--qt-runtime' in argv:
        index=argv.index('--qt-runtime')
        if index+1>=len(argv):raise ValueError('请指定本地 Qt 运行库目录')
        value=argv[index+1]
    if not value:return None
    root=Path(value).expanduser()
    if str(root).startswith('\\\\') or not root.is_absolute():raise ValueError('Qt 替换运行库必须位于本地绝对路径')
    root=root.resolve()
    for relative in ('PySide6/__init__.py','shiboken6/__init__.py','PySide6/Qt6Core.dll',
                     'PySide6/Qt6Gui.dll','PySide6/Qt6Widgets.dll','PySide6/Qt6Svg.dll'):
        if not (root/relative).is_file():raise ValueError('Qt 替换运行库不完整，请参阅组件替换说明')
    if not getattr(sys,'_splitguard_qt_override',None):
        if any(name.startswith('PySide6.Qt') for name in sys.modules):raise RuntimeError('必须在 Qt 初始化前指定替换运行库')
        sys.path.insert(0,str(root));sys._splitguard_qt_override=str(root)
        if os.name=='nt':
            sys._splitguard_dll_dirs=[os.add_dll_directory(str(root/name)) for name in ('PySide6','shiboken6')]
    os.environ[ENV]=str(root)
    # The standard PyInstaller Qt hook may set this again between bootstrap and main.
    os.environ['QT_PLUGIN_PATH']=str(root/'PySide6'/'plugins')
    os.environ['QML2_IMPORT_PATH']=str(root/'PySide6'/'qml')
    return root


def verify_runtime_override():
    """Check the optional replacement without publishing a user's local paths."""
    value=getattr(sys,'_splitguard_qt_override',None)
    if not value:return False
    root=Path(value)
    import PySide6
    from PySide6 import QtCore,QtGui,QtWidgets,QtSvg
    import shiboken6
    for module in (PySide6,QtCore,QtGui,QtWidgets,QtSvg,shiboken6):
        assert Path(module.__file__).resolve().is_relative_to(root), 'Qt replacement module was not used'
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];kernel.GetModuleHandleW.restype=ctypes.c_void_p
        kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
        for name in ('Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','Qt6Svg.dll'):
            module=kernel.GetModuleHandleW(name);buffer=ctypes.create_unicode_buffer(32768)
            assert module and kernel.GetModuleFileNameW(module,buffer,len(buffer))
            assert Path(buffer.value).resolve().is_relative_to(root), 'Qt replacement DLL was not used'
    return True
