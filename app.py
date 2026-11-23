from __future__ import annotations
import argparse
import json
import sys
from guard.common import DATA, DEFAULTS, read_json, save_json


def main():
    parser=argparse.ArgumentParser(description='v2rayN 分流助手')
    parser.add_argument('--worker',nargs=3,metavar=('REQUEST','RESULT','SHA256'),help=argparse.SUPPRESS)
    parser.add_argument('--diagnose',action='store_true',help='只读诊断，输出脱敏结果，不修改网络')
    parser.add_argument('--proxy-test',action='store_true',help='诊断时主动测试 SOCKS5h HTTPS')
    parser.add_argument('--output',help='脱敏诊断 JSON 输出路径')
    parser.add_argument('--ui-self-test',action='store_true',help='验证打包的 Qt 可以初始化，不读取网络')
    parser.add_argument('--qt-ui-test',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--preview',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--qt-runtime',help=argparse.SUPPRESS)
    parser.add_argument('--runtime-self-test',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--exit-self-test',metavar='SCENARIO',help=argparse.SUPPRESS)
    args=parser.parse_args()
    from guard.qt_runtime import apply_runtime_override
    apply_runtime_override(sys.argv)
    if args.worker:
        from guard.elevation import worker
        worker(*args.worker)
    elif args.runtime_self_test:
        try:
            from guard.runtimecheck import run
            result=run()
        except Exception as e:
            result=dict(ok=False,error=str(e))
        if args.output:save_json(args.output,result)
        if sys.stdout is not None:print(json.dumps(result,ensure_ascii=False))
        if not result['ok']:sys.exit(1)
    elif args.exit_self_test:
        try:
            from guard.exitcheck import run
            result=run(args.exit_self_test)
        except Exception as e:
            result=dict(ok=False,error=str(e))
        if args.output:save_json(args.output,result)
        if sys.stdout is not None:print(json.dumps(result,ensure_ascii=False))
        if not result['ok']:sys.exit(1)
    elif args.qt_ui_test or args.preview:
        from guard.qtcheck import smoke
        result=smoke(preview=args.preview)
        if args.output:save_json(args.output,result)
        if sys.stdout is not None:print(json.dumps(result,ensure_ascii=False))
    elif args.ui_self_test:
        try:
            from PySide6.QtWidgets import QApplication,QWidget
            from PySide6.QtCore import qVersion
            app=QApplication([]);root=QWidget();root.resize(200,100);root.show();app.processEvents()
            from guard.qt_runtime import verify_runtime_override
            result=dict(ok=True,qt=qVersion(),ui='PySide6 / Qt Widgets',
                        runtime_override_verified=verify_runtime_override());root.close();app.processEvents()
        except Exception as e:
            result=dict(ok=False,error=str(e))
        if args.output:save_json(args.output,result)
        if sys.stdout is not None:print(json.dumps(result,ensure_ascii=False))
        if not result['ok']:sys.exit(1)
    elif args.diagnose:
        from guard.network import check,test_proxy
        from guard.privacy import public_diagnostic
        config=dict(DEFAULTS,**(read_json(DATA/'settings.json',{}) or {}))
        r=check(config)
        if args.proxy_test:r['proxy_test']=test_proxy(config=config)
        r=public_diagnostic(r)
        if args.output:save_json(args.output,r)
        if sys.stdout is not None:
            print(json.dumps(r,ensure_ascii=False,indent=2))
    else:
        from guard.ui import main as gui
        gui()


if __name__=='__main__':
    main()
