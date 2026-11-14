import copy
import json
import threading
import time
from unittest.mock import patch,Mock
from PySide6.QtCore import Qt,QThread,QCoreApplication,QEvent
from PySide6.QtWidgets import QDialog,QPushButton,QApplication
from PySide6.QtTest import QTest
from guard.common import VERSION
from guard.close_prompt import CLOSE_CHOICES
from guard.notifications import NotificationManager
from qt_support import QtCase,QAPP,pump_until


class QtWindowTests(QtCase):
    def test_four_pages_and_no_removed_sidebar_actions(self):
        self.assertEqual(self.app.pages.count(),4)
        for index,name in enumerate(('状态总览','备份恢复','诊断日志','高级设置')):
            self.app.nav_buttons[name].click();self.assertEqual(self.app.pages.currentIndex(),index)
            self.assertTrue(self.app.nav_buttons[name].isChecked())
        names=[b.text() for b in self.app.sidebar.findChildren(QPushButton)]
        self.assertNotIn('退出程序',names);self.assertNotIn('最小化到托盘',names)

    def test_report_ipv4_ipv6_and_proxy_evidence_invalidation(self):
        self.app.show_report(self.report)
        self.assertEqual(self.app.table.model().rowCount(),2)
        self.assertEqual(self.app.route_label.text(),'路由分流正常')
        self.app.show_proxy(dict(ok=True,ip='192.0.2.4',time=self.report['time'],message='模拟'))
        other=copy.deepcopy(self.report);other['wlan']['gateway']='10.0.0.3'
        self.app.show_report(other)
        self.assertIsNone(self.app.proxy);self.assertEqual(self.app.proxy_label.text(),'尚未测试')
        self.assertIn('change.gateway',self.app.notifications.state.records)

    def test_wrong_ipv6_route_prevents_all_success(self):
        self.report['rows'][1].update(ok=False,via_wlan=False)
        self.report['faults']=['节点选路未经过 WLAN：2001:db8::10']
        self.app.show_report(self.report)
        self.assertEqual(self.app.route_label.text(),'路由异常 / 待检查')

    def test_worker_is_background_and_result_callback_is_main_thread(self):
        threads=[];ready=threading.Event()
        self.app.task('模拟任务',lambda:(threads.append(QThread.currentThread()),ready.wait(.05),7)[-1],
                      lambda value:threads.append((QThread.currentThread(),value)))
        self.assertTrue(self.app.busy);self.assertFalse(self.app.check_button.isEnabled())
        self.app.navigate(3);self.assertEqual(self.app.pages.currentIndex(),3)
        pump_until(lambda:not self.app.busy)
        self.assertIsNot(threads[0],QAPP.thread());self.assertIs(threads[1][0],QAPP.thread());self.assertEqual(threads[1][1],7)

    def test_failure_releases_busy_controls(self):
        def fail():raise RuntimeError('模拟失败')
        self.app.task('模拟任务',fail,lambda value:None);pump_until(lambda:not self.app.busy)
        self.assertTrue(self.app.check_button.isEnabled());self.assertIn('模拟失败',self.app.status.text())

    def test_close_default_singleton_and_cancel(self):
        self.app.close();first=self.app.close_prompt
        self.assertEqual(first.selected_action(),'tray');self.assertFalse(first.remember.isChecked())
        self.app.request_close();self.assertIs(self.app.close_prompt,first)
        first.remember.setChecked(True);first.exit_radio.setChecked(True);first.cancel_button.click()
        self.assertIsNone(self.app.close_prompt);self.assertFalse(self.app.closing)
        self.assertFalse((self.data/'settings.json').exists())

    def test_close_escape_cancels(self):
        self.app.request_close();QTest.keyClick(self.app.close_prompt,Qt.Key.Key_Escape)
        self.assertIsNone(self.app.close_prompt);self.assertFalse(self.app.closing)

    def test_close_minimize_falls_back_to_taskbar(self):
        self.app.request_close()
        with patch.object(self.app,'showMinimized') as minimize:self.app.close_prompt.confirm_button.click()
        minimize.assert_called_once();self.assertFalse(self.app.stop.is_set())

    def test_remember_close_persists_before_exit(self):
        self.app.request_close();win=self.app.close_prompt;win.exit_radio.setChecked(True);win.remember.setChecked(True)
        win.confirm_button.click()
        self.assertTrue(self.app._destroyed)
        self.assertEqual(json.loads((self.data/'settings.json').read_text(encoding='utf-8'))['close_action'],'exit')

    def test_remember_close_save_failure_keeps_choice_open(self):
        self.app.request_close();win=self.app.close_prompt;win.remember.setChecked(True)
        with patch('guard.ui.save_json',side_effect=OSError('PRIVATE_SENTINEL')),patch.object(self.app,'error') as error:
            win.confirm_button.click()
        self.assertIs(self.app.close_prompt,win);self.assertFalse(self.app.closing)
        self.assertNotIn('PRIVATE_SENTINEL',str(error.call_args))

    def test_exit_waits_for_task_and_skips_its_callback(self):
        callback=Mock();self.app.task('模拟任务',lambda:self.app.stop.wait(2),callback)
        self.app.quit();self.assertTrue(self.app.closing);self.assertFalse(self.app._destroyed)
        pump_until(lambda:self.app._destroyed);callback.assert_not_called()

    def test_saved_close_actions_and_invalid_fallback(self):
        self.app.config['close_action']='tray'
        with patch.object(self.app,'minimize') as minimize:self.app.request_close()
        minimize.assert_called_once();self.assertIsNone(self.app.close_prompt)
        self.app.config['close_action']='invalid';self.app.request_close();self.assertIsNotNone(self.app.close_prompt)
        self.app.dismiss_close_prompt();self.app.config['close_action']='exit';self.app.request_close();self.assertTrue(self.app._destroyed)

    def test_settings_are_draft_until_save_and_restore(self):
        self.app.settings_fields['company'].setText('示例拨号');self.app.close_action_menu.setCurrentText('直接退出程序')
        self.app.navigate(0);self.app.navigate(3)
        self.assertNotEqual(self.app.config['company'],'示例拨号');self.assertEqual(self.app.settings_fields['company'].text(),'示例拨号')
        self.app.reset_settings();self.assertNotEqual(self.app.settings_fields['company'].text(),'示例拨号')
        for text,value in CLOSE_CHOICES.items():
            self.app.close_action_menu.setCurrentText(text)
            with patch.object(self.app,'do_check'):self.app.save_settings()
            self.assertEqual(self.app.config['close_action'],value)
            self.assertEqual(json.loads((self.data/'settings.json').read_text(encoding='utf-8'))['close_action'],value)

    def test_settings_reject_missing_or_unspecified_gateway(self):
        self.app.settings_fields['gateway'].setText('0.0.0.0')
        with patch.object(self.app,'error') as error:self.app.save_settings()
        error.assert_called_once();self.assertEqual(self.app.config['gateway'],'')

    def test_detection_draft_and_late_user_edit(self):
        picker=self.app.runtime_picker
        result=dict(candidates=[dict(path='detected.json',source='测试核心参数',pid=123)],automatic='detected.json',notes=[],cancelled=False)
        jobs=[];picker.start_task=lambda work,done:jobs.append((work,done)) or True
        picker.detect();picker.path.setText('edited.json');jobs[-1][1](result)
        self.assertEqual(picker.path.text(),'edited.json')
        picker.adopt();self.assertEqual(picker.path.text(),'detected.json');self.assertEqual(self.app.config['runtime'],'')

    def test_cancel_settings_invalidates_pending_detection(self):
        picker=self.app.runtime_picker;jobs=[];picker.start_task=lambda work,done:jobs.append(done) or True
        picker.detect();self.app.reset_settings()
        jobs[-1](dict(candidates=[],automatic='unexpected.json',notes=[],cancelled=False))
        self.assertEqual(picker.path.text(),self.app.config['runtime'])

    def test_log_is_plain_text_and_tail_only(self):
        (self.data/'diagnostics.log').write_text('a'*110000+'<img src="file:///private">',encoding='utf-8')
        self.app.refresh_log();text=self.app.log_text.toPlainText()
        self.assertLessEqual(len(text),100000);self.assertIn('<img src=',text)

    def test_route_preview_never_mutates_until_explicit_apply(self):
        self.app.show_report(self.report)
        with patch.object(self.app,'apply_plan') as apply:
            win=self.app.route_dialog(self.report,dict(self.app.config))
            self.assertIn('203.0.113.10',win.preview.toPlainText());apply.assert_not_called()
            win.reject();apply.assert_not_called()

    def test_route_preview_requires_explicit_takeover(self):
        self.report['net']['routes'][0]['gateway']='10.0.0.9'
        win=self.app.route_dialog(self.report,dict(self.app.config))
        before=win.preview.toPlainText();win.adopt.setChecked(True)
        self.assertNotEqual(before,win.preview.toPlainText());self.assertIn('接管现有路由：是',win.preview.toPlainText())

    def test_backup_page_lists_only_local_json_without_restoring(self):
        folder=self.data/'backups';folder.mkdir();(folder/'sample.json').write_text('{}');(folder/'ignore.txt').write_text('x')
        self.app.navigate(1);self.assertEqual(self.app.backup_list.count(),1)
        self.app.backup_list.setCurrentRow(0);self.assertTrue(self.app.backup_path.text().endswith('sample.json'))
        self.assertFalse(self.app.busy)

    def test_auto_gateway_only_saves_tool_preference(self):
        self.app.config.update(gateway='10.0.0.9',gateway6='fe80::9')
        with patch.object(self.app,'do_check') as check:self.app.auto_gateway()
        self.assertEqual(self.app.config['gateway'],'');self.assertEqual(self.app.config['gateway6'],'');check.assert_called_once()

    def test_labels_do_not_interpret_config_html(self):
        self.report['warnings']=['<img src="file:///private">'];self.app.show_report(self.report)
        self.assertEqual(self.app.node_hint.textFormat(),Qt.TextFormat.PlainText)

    def test_notifications_merge_eight_hours_and_reuse_manual_window(self):
        clock=[0];manager=self.app.notifications;manager.state.clock=lambda:clock[0]
        failure=dict(ok=False,ip='',time=self.report['time'],message='模拟超时')
        for i in range(480):clock[0]=i*60;self.app.show_proxy(failure,automatic=True)
        win=manager.window;manager.show_details();self.assertIs(manager.window,win)
        self.assertEqual(manager.state.unread_count,1);self.assertEqual(manager.state.active_count,1)
        self.assertFalse(manager.timer.isActive());manager.acknowledge();self.app.show_proxy(failure,automatic=True)
        self.assertIsNone(manager.window);self.assertEqual(self.app.proxy_label.text(),'代理测试失败')

    def test_notification_auto_hide_stays_unread(self):
        manager=self.app.notifications;manager.auto_close_ms=1
        manager.update({'x':('模拟','失败')});pump_until(lambda:manager.window is None)
        self.assertEqual(manager.state.unread_count,1);manager.update({'x':('模拟','仍失败')});self.assertIsNone(manager.window)

    def test_notification_escape_acknowledges(self):
        manager=self.app.notifications;manager.update({'x':('模拟','失败')})
        QTest.keyClick(manager.window,Qt.Key.Key_Escape)
        self.assertIsNone(manager.window);self.assertEqual(manager.state.unread_count,0)

    def test_close_prompt_defers_background_notification(self):
        self.app.request_close();self.app.show_proxy(dict(ok=False,ip='',time=self.report['time'],message='模拟'),automatic=True)
        self.assertIsNone(self.app.notifications.window);self.app.close_prompt.reject();self.app.notifications.flush()
        self.assertIsNotNone(self.app.notifications.window)

    def test_existing_settings_are_compatible_and_unsaved_form_is_not_collected(self):
        self.app.settings_fields['company'].setText('未保存草稿')
        cfg=self.app.collect();self.assertNotEqual(cfg['company'],'未保存草稿')
        self.assertEqual(cfg['close_action'],'ask');self.assertIn('runtime',cfg)
