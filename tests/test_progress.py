import copy
import threading
import time
from unittest.mock import patch,Mock
from PySide6.QtCore import QTimer,QThread
from PySide6.QtWidgets import QPlainTextEdit
from guard.common import check_cancelled
from guard.routes import plan_routes
from qt_support import QtCase,QAPP,pump_until


class ProgressTests(QtCase):
    def test_preview_progress_visible_before_query_finishes_and_heartbeat_runs(self):
        gate=threading.Event();beats=[];timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:beats.append(1));timer.start()
        def check(cfg,stop,progress):
            progress('解析节点 A / AAAA 地址');gate.wait(.3);check_cancelled(stop);return self.report
        with patch('guard.ui.check',check):
            self.app.prepare_routes();win=self.app._operation
            self.assertTrue(win.isVisible());self.assertTrue(self.app.busy);self.assertFalse(self.app._dialogs)
            pump_until(lambda:len(beats)>=4);self.assertIn('A / AAAA',win.stage_label.text())
            gate.set();pump_until(lambda:not self.app.busy)
        timer.stop();self.assertIsNone(self.app._operation);self.assertEqual(self.app._dialogs[-1].windowTitle(),'路由变更预览')
    def test_readonly_cancel_never_opens_preview_and_next_operation_works(self):
        def check(cfg,stop,progress):stop.wait(.5);check_cancelled(stop);return self.report
        with patch('guard.ui.check',check):
            self.app.prepare_routes();self.app._operation.cancel_button.click();pump_until(lambda:not self.app.busy)
        self.assertIsNone(self.app._operation);self.assertFalse(self.app._dialogs);self.assertFalse(self.app.stop.is_set())
        self.app.prepare_routes();pump_until(lambda:not self.app.busy);self.assertTrue(self.app._dialogs)
    def test_escape_requests_cancel_but_keeps_progress_until_worker_finishes(self):
        gate=threading.Event()
        def check(cfg,stop,progress):gate.wait(.3);check_cancelled(stop);return self.report
        with patch('guard.ui.check',check):
            self.app.prepare_routes();win=self.app._operation;win.reject()
            self.assertTrue(win.isVisible());self.assertTrue(win.token.is_set())
            gate.set();pump_until(lambda:not self.app.busy)
        self.assertFalse(self.app._dialogs)
    def test_query_failure_closes_progress_and_reports_error(self):
        with patch('guard.ui.check',side_effect=TimeoutError('查询超时')),patch.object(self.app,'error') as error:
            self.app.prepare_routes();pump_until(lambda:not self.app.busy)
        self.assertIsNone(self.app._operation);error.assert_called_once();self.assertTrue(self.app.repair_button.isEnabled())
    def test_noop_result_does_not_start_another_full_check(self):
        plan=plan_routes(self.report,self.app.config,[])
        def execute(plan,**kwargs):
            kwargs['progress']('核对 WLAN、网关及两个路由存储');kwargs['stop'].wait(.04)
            return dict(ok=True,route_changed=False,backup='',message='核验通过；未修改路由')
        with patch('guard.ui.execute',execute),patch.object(self.app,'do_check') as check:
            self.app.apply_plan(plan);self.assertTrue(self.app._operation.isVisible());pump_until(lambda:not self.app.busy)
        check.assert_not_called();self.assertIn('未修改路由',self.app._dialogs[-1].findChild(QPlainTextEdit).toPlainText())
    def test_write_operation_cannot_be_cancelled_and_still_waits_for_completion(self):
        plan=plan_routes(self.report,self.app.config,[]);plan['creates']=[plan['after'][0]];gate=threading.Event();token=[]
        def elevated(*args,progress=None):progress('备份变更前记录');gate.wait(.4);return dict(ok=True,route_changed=True,backup='',message='模拟完成')
        with patch('guard.ui.elevated_job',elevated),patch.object(self.app,'do_check'):
            self.app.apply_plan(plan);win=self.app._operation
            self.assertFalse(win.cancellable);win.reject();self.assertFalse(win.token.is_set());self.assertTrue(win.isVisible())
            gate.set();pump_until(lambda:not self.app.busy)
        self.assertIsNone(self.app._operation)
    def test_quit_stops_readonly_operation_without_late_preview(self):
        def check(cfg,stop,progress):stop.wait(.5);check_cancelled(stop);return self.report
        with patch('guard.ui.check',check):
            self.app.prepare_routes();self.app.quit();pump_until(lambda:self.app._destroyed)
        self.assertIsNone(self.app._operation);self.assertFalse(self.app._dialogs)
