"""Isolated native-Qt integration checks, also callable inside the final EXE."""
import logging
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from PySide6.QtCore import Qt,QTimer,qInstallMessageHandler,qVersion
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QSystemTrayIcon,QStyle
from .theme import configure_application
from .ui import Application
from .samples import report_fixture


def pump(app,predicate,timeout=5):
    end=time.monotonic()+timeout
    while not predicate():
        app.processEvents();time.sleep(.005)
        if time.monotonic()>end:raise AssertionError('Qt event loop timed out')
    app.processEvents()


def smoke(*,real_tray=False,preview=False):
    app=QApplication.instance() or QApplication([]);configure_application(app)
    warnings=[];previous=qInstallMessageHandler(lambda kind,context,message:warnings.append(message))
    passed=[];report=report_fixture()
    try:
        with tempfile.TemporaryDirectory(prefix='split-guard-qt-') as temp, \
             patch('guard.ui.check',return_value=report), \
             patch('guard.ui.test_proxy',return_value=dict(ok=True,ip='192.0.2.4',time=report['time'],message='模拟成功')), \
             patch('guard.ui.elevated_job',side_effect=AssertionError('UI preview cannot write routes')), \
             patch('guard.ui.execute',side_effect=AssertionError('UI preview cannot write routes')):
            data=Path(temp);window=Application(data_dir=data,autorun=False,tray_enabled=real_tray,logger=logging.getLogger('qt-smoke'))
            window.monitor.setChecked(False);window.auto_proxy.setChecked(False);window.show_report(report);window.show();app.processEvents()
            if preview:
                window.setWindowTitle('v2rayN 分流助手 — Qt 预览（示例数据）')
                QTimer.singleShot(600000,window.quit);app.exec()
                return dict(ok=True,network_writes=0)
            assert window.pages.count()==4 and window.table.model().rowCount()==2
            assert window.route_label.text()=='路由分流正常'
            passed.append('IPv4/IPv6 路由、网络和节点状态渲染')
            for i,item in enumerate(window.nav_buttons.values()):
                item.click();app.processEvents();assert window.pages.currentIndex()==i and item.isChecked()
            assert window.close_action_menu.isVisible()
            assert set(window.close_action_menu.itemText(i) for i in range(3))=={'每次询问','直接退出程序','最小化到托盘'}
            assert window.close_action_menu.mapTo(window,window.close_action_menu.rect().topLeft()).y()<210
            menu=window.close_action_menu;menu.showPopup();app.processEvents()
            assert menu.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup)==0
            last=menu.view().visualRect(menu.model().index(menu.count()-1,0))
            assert menu.view().viewport().rect().contains(last), '关闭方式弹层裁切选项'
            menu.hidePopup()
            passed.append('四个独立页面、顶部关闭设置和侧栏导航')
            initial=window.config['runtime'];detected=str(data/'示例配置.json')
            with patch('guard.config_picker.discover_runtime',return_value=dict(candidates=[dict(path=detected,source='示例核心',pid=123)],automatic=detected,notes=[],cancelled=False)):
                window.runtime_picker.detect();pump(app,lambda:not window.busy)
            assert window.runtime_picker.path.text()==detected and window.config['runtime']==initial
            assert not (data/'settings.json').exists()
            window.reset_settings();passed.append('异步配置检测只修改草稿、可放弃')
            dialog=window.route_dialog(report,dict(window.config));app.processEvents()
            assert dialog.isVisible() and '203.0.113.10' in dialog.preview.toPlainText()
            dialog.reject();app.processEvents();passed.append('路由预览创建和取消，不提权、不写路由')
            from .common import check_cancelled
            def cancellable_check(config,stop,progress):
                progress('解析节点 A / AAAA 地址');stop.wait(.15);check_cancelled(stop);return report
            with patch('guard.ui.check',cancellable_check):
                window.prepare_routes();operation=window._operation
                assert operation.isVisible() and operation.cancellable
                work=window.screen().availableGeometry()
                assert operation.width()<=work.width() and operation.height()<=work.height()
                app.processEvents();operation.cancel_button.click();pump(app,lambda:not window.busy)
            assert window._operation is None and not window.stop.is_set()
            passed.append('即时进度、只读取消及不同 DPI 下进度窗口可访问')
            from .routes import plan_routes,execute
            plan=plan_routes(report,window.config,[])
            with patch('guard.nodes.resolve',return_value=report['addresses']),patch('guard.routes.snapshot',return_value=report['net']) as reads,patch('guard.routes.wlan_info',return_value=report['wlan']),patch('guard.routes.read_routes',side_effect=AssertionError('重复读取')),patch('guard.routes.run',side_effect=AssertionError('真实写入被禁止')):
                result=execute(plan,backup_dir=data/'backups',ledger_path=data/'managed.json')
            assert reads.call_count==1 and result['route_changed'] is False and not result['backup']
            passed.append('无变更仅一次快照、双存储核验且不写路由')
            window.request_close();first=window.close_prompt;window.request_close();assert window.close_prompt is first
            assert first.selected_action()=='tray';first.cancel_button.click();app.processEvents()
            assert window.close_prompt is None and not window.closing
            passed.append('关闭选择单实例、默认最小化和取消')
            manager=window.notifications;sender=manager.notify;manager.notify=lambda *args:False
            failure={'proxy_https':('代理测试失败','模拟超时')}
            manager.update(failure);first=manager.window
            for _ in range(100):manager.update(failure)
            manager.show_details();assert manager.window is first and not manager.timer.isActive()
            manager.acknowledge();manager.update(failure);assert manager.window is None and manager.state.active_count==1
            manager.update({});manager.notify=sender;passed.append('提醒合并、窗口复用和知晓后静默')
            # The complete native window, rather than only one table, must fit its work area.
            work=window.screen().availableGeometry();assert window.width()<=work.width() and window.height()<=work.height()
            window.navigate(3);app.processEvents();assert window.save_settings_button.isVisible()
            point=window.save_settings_button.mapTo(window,window.save_settings_button.rect().bottomRight())
            assert point.x()<=window.width() and point.y()<=window.height()
            sidebar=[b.text() for b in window.sidebar.findChildren(QPushButton)]
            assert '最小化到托盘' not in sidebar and '退出程序' not in sidebar
            passed.append('逻辑 DPI 工作区适配、侧栏精简和关键按钮可访问')
            if real_tray:assert window.tray is not None and window.tray.isVisible()
            window.task('退出测试',lambda:window.stop.wait(2),lambda result:None)
            window.quit();pump(app,lambda:window._destroyed)
            assert window._thread is None
            passed.append('后台任务可停止、等待结束后安全退出')
            severe=[s for s in warnings if any(key in s for key in ('QThread: Destroyed','Cannot create children','QObject::killTimer','Unknown property'))]
            assert not severe,severe
            return dict(ok=True,toolkit='PySide6 / Qt Widgets',qt=qVersion(),passed=passed,
                        device_pixel_ratio=window.devicePixelRatioF(),real_tray=real_tray,
                        warnings=severe,network_writes=0)
    finally:qInstallMessageHandler(previous)
