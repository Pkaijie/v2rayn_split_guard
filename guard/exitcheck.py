"""Each scenario runs in a separate process with a real Windows Qt tray."""
import logging
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from PySide6.QtCore import QTimer,qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from .ui import Application
from .theme import configure_application

SCENARIOS=('idle_click','busy_click','failed_task','repeat_exit','tray_idle','tray_busy','open_dialog',
           'reminder_open','reminder_hidden','close_exit','close_busy','close_cancel','close_minimize','settings_detection',
           'progress_readonly','progress_transaction')


def run(scenario):
    if scenario not in SCENARIOS:raise ValueError('未知退出自检场景')
    app=QApplication([]);configure_application(app);errors=[]
    previous=qInstallMessageHandler(lambda kind,context,message:errors.append(message))
    try:
        def detecting(token):
            deadline=time.monotonic()+2
            while not token.is_set() and time.monotonic()<deadline:time.sleep(.01)
            return dict(candidates=[],automatic='',cancelled=token.is_set(),notes=['模拟取消扫描'])
        with tempfile.TemporaryDirectory(prefix='split-guard-exit-') as tmp, patch('guard.config_picker.discover_runtime',detecting):
            window=Application(data_dir=Path(tmp),autorun=False,logger=logging.getLogger('qt-exit'))
            window.monitor.setChecked(False);window.auto_proxy.setChecked(False);window.config['close_action']='ask'
            result_errors=[]
            def click_exit():
                window.request_close();window.close_prompt.exit_radio.setChecked(True);window.close_prompt.confirm_button.click()
                if scenario=='repeat_exit':window.quit()
            def stop():
                try:
                    if scenario in ('busy_click','failed_task','tray_busy','close_busy'):
                        def work():
                            window.stop.wait(2)
                            if scenario=='failed_task':raise RuntimeError('模拟取消任务')
                        window.task('退出回归',work,lambda result:None)
                    if scenario=='settings_detection':
                        window.navigate(3);window.runtime_picker.detect()
                        assert window.busy
                    if scenario in ('progress_readonly','progress_transaction'):
                        def work(token,progress):
                            progress('模拟后台核验')
                            if scenario=='progress_readonly':token.wait(.5)
                            else:time.sleep(.25)
                        window.task('进度退出回归',work,lambda result:None,operation=True,cancellable=scenario=='progress_readonly')
                        assert window._operation.isVisible()
                        window.quit();return
                    if scenario=='open_dialog':window.text_window('退出测试','仅用于验证子窗口清理')
                    if scenario in ('reminder_open','reminder_hidden'):
                        window.notifications.notify=lambda *args:False
                        if scenario=='reminder_hidden':window.notifications.auto_close_ms=1
                        window.notifications.update({'proxy_https':('代理测试失败','模拟超时')})
                        if scenario=='reminder_hidden':QTimer.singleShot(30,window.quit);return
                    if scenario in ('tray_idle','tray_busy','open_dialog','reminder_open','settings_detection'):
                        action=next(a for a in window.tray.contextMenu().actions() if a.text()=='退出')
                        action.trigger();return
                    if scenario=='close_cancel':
                        window.request_close();window.close_prompt.cancel_button.click();assert window.close_prompt is None and not window.closing
                    if scenario=='close_minimize':
                        window.request_close();window.close_prompt.confirm_button.click();assert not window.isVisible() and not window.closing
                        QTimer.singleShot(20,window.quit);return
                    click_exit()
                except Exception as error:result_errors.append(str(error));window.quit()
            window.show();QTimer.singleShot(150,stop)
            started=time.monotonic();app.exec()
            severe=[s for s in errors if any(k in s for k in ('QThread: Destroyed','QObject::killTimer','Cannot create children'))]
            result_errors+=severe
            return dict(ok=window._destroyed and not result_errors,scenario=scenario,
                elapsed=round(time.monotonic()-started,3),errors=result_errors,real_tray=window.tray is not None,network_writes=0)
    finally:qInstallMessageHandler(previous)
