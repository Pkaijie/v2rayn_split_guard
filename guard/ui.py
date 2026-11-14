"""Qt controller. Workers never access widgets and never change routes implicitly."""
from __future__ import annotations
import ipaddress
import json
import os
from pathlib import Path
import threading
import time
from PySide6.QtCore import Qt,QThread,QTimer,Signal,Slot
from PySide6.QtGui import QAction,QIcon,QKeySequence
from PySide6.QtWidgets import (QApplication,QMainWindow,QSystemTrayIcon,QMenu,QMessageBox,
    QVBoxLayout,QHBoxLayout,QCheckBox,QFileDialog,QListWidgetItem)
from shiboken6 import isValid
from .common import DATA,DEFAULTS,VERSION,read_json,save_json,setup_log,timestamp
from .network import check,test_proxy
from .routes import plan_routes,preview_text,restore_plan,execute
from .elevation import elevated_job
from .notifications import NotificationManager,fault_snapshot
from .close_prompt import ClosePrompt,CLOSE_CHOICES
from .progress import OperationDialog,OperationToken
from .common import OperationCancelled
from .theme import *
from .views import build


def fingerprint(report):
    return json.dumps([report['wlan'],report['company'],report['node'],report['addresses'],report['listener'],
        [(r['ip'],r['chosen'],r['exact']) for r in report['rows']]],sort_keys=True)


class WorkThread(QThread):
    completed=Signal(object)
    advanced=Signal(str)
    def __init__(self,work,parent,token=None):super().__init__(parent);self.work=work;self.token=token
    def run(self):
        try:result=dict(ok=True,result=self.work(self.token,self.advanced.emit) if self.token is not None else self.work())
        except OperationCancelled:result=dict(ok=False,cancelled=True,message='操作已取消')
        except Exception as error:result=dict(ok=False,message=str(error)[:1500])
        self.completed.emit(result)


class Application(QMainWindow):
    def __init__(self,*,data_dir=None,autorun=True,tray_enabled=True,logger=None):
        super().__init__();self.data=Path(data_dir) if data_dir is not None else DATA
        self.log=logger if logger is not None else setup_log()
        self.config=dict(DEFAULTS,**(read_json(self.data/'settings.json',{}) or {}))
        self.stop=threading.Event();self.busy=False;self.closing=False;self._destroyed=False;self._allow_close=False
        self.report=None;self.proxy=None;self.last_check=0;self.last_proxy=0;self.tray=None;self.close_prompt=None
        self._thread=None;self._job_result=None;self._dialogs=[];self._backup=None;self._settings_dirty=False;self._operation=None
        build(self)
        self.notifications=NotificationManager(self,notify=self._send_tray_reminder,
            on_change=self.update_notification_badge,cooldown=self.config['cooldown'])
        self.update_notification_badge();self.reset_settings()
        if tray_enabled:self.init_tray()
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.poll);self.timer.start()
        self.startup_timer=QTimer(self);self.startup_timer.setSingleShot(True);self.startup_timer.timeout.connect(self.do_check)
        if autorun:self.startup_timer.start(200)
        refresh=QAction('立即检查',self);refresh.setShortcut(QKeySequence('Ctrl+R'));refresh.triggered.connect(self.do_check);self.addAction(refresh)

    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        for i,item in enumerate(self.nav_buttons.values()):item.setChecked(i==index)
        if index==1:self.refresh_backups()
        elif index==2:self.refresh_log()

    def collect(self):
        cfg=dict(self.config)
        if cfg.get('runtime'):cfg['runtime']=str(Path(os.path.expandvars(cfg['runtime'])).expanduser().resolve())
        cfg.update(manual=self.manual.isChecked(),host=self.host.text().strip(),port=self.port.value(),
            protocol=self.protocol.text().strip(),transport=self.transport.currentText(),tag=self.combo.currentText(),
            interval=self.interval.value(),auto_proxy=self.auto_proxy.isChecked())
        if cfg['manual']:
            from .nodes import make_node
            make_node('手动',cfg['host'],cfg['port'],cfg['protocol'],cfg['transport'])
        if cfg!=self.config or not (self.data/'settings.json').exists():save_json(self.data/'settings.json',cfg)
        self.config=cfg;return dict(cfg)

    def task(self,title,work,callback,*,operation=False,cancellable=False):
        if self.busy or self.closing:return False
        self.busy=True;self._job_callback=callback;self._job_title=title;self._job_result=None;self._thread_was_operation=operation
        self._set_busy(True);self.status.setText(title+'… 窗口可继续操作')
        token=OperationToken(self.stop) if operation else None
        if operation:
            self._operation=OperationDialog(self,title,token,cancellable);self._operation.show()
        self._thread=WorkThread(work,self,token);self._thread.completed.connect(self._task_result)
        self._thread.advanced.connect(self._task_progress)
        self._thread.finished.connect(self._task_finished);self._thread.start();return True

    def _set_busy(self,busy):
        for control in (self.check_button,self.repair_button,self.proxy_button,self.gateway_button,
                        self.apply_input_button,self.restore_button,self.save_settings_button):control.setEnabled(not busy)

    @Slot(object)
    def _task_result(self,result):self._job_result=result

    @Slot(str)
    def _task_progress(self,text):
        if self._operation is not None and not self._operation.token.is_set():self._operation.stage_label.setText(text)
        if self._operation is not None and text in ('备份变更前记录','保存已确认的管理范围'):
            self._operation.cancellable=False;self._operation.cancel_button.setEnabled(False)
        if not self.closing:self.status.setText(text+'…')

    @Slot()
    def _task_finished(self):
        thread,self._thread=self._thread,None
        if thread is not None:thread.deleteLater()
        if self._operation is not None:self._operation.finish();self._operation=None
        self.busy=False;self._set_busy(False)
        if self.closing:self.finish_quit();return
        result=self._job_result
        if result and result['ok']:
            try:
                self._job_callback(result['result'])
                if not self.busy and not self.closing:self.status.setText('已更新 · '+timestamp())
            except Exception as error:
                self.log.exception('处理检查结果失败');self.status.setText('处理结果失败：'+str(error)[:180])
        elif result and result.get('cancelled'):
            self.status.setText('操作已取消，未执行路由变更。');self.last_check=time.monotonic()
        else:
            message=(result or {}).get('message','后台任务未返回结果')
            self.status.setText(self._job_title+'失败：'+message[:180]);self.log.error('%s %s',self._job_title,message)
            self.last_check=time.monotonic()
            if self._thread_was_operation:self.error(self._job_title+'失败',message)

    def changed(self):
        if self.busy or self.closing:self.notice.setText('请等待当前任务完成后再应用输入。');return
        try:self.collect();self.invalidate('节点输入已变化');self.do_check()
        except (ValueError,OSError) as error:self.error('输入不正确',str(error))

    def select_node(self,index):self.manual.setChecked(False);self.changed()

    def invalidate(self,reason):
        self.proxy=None;self.proxy_label.setText('尚未测试');set_color(self.proxy_label,WHITE,24,True)
        self.proxy_detail.setText('请重新测试')

    def do_check(self):
        if self.busy or self.closing:return
        try:cfg=self.collect()
        except (ValueError,OSError):
            self.status.setText('输入或设置保存失败，请核对端口、域名和设置目录权限。');self.last_check=time.monotonic();return
        self.task('正在读取网络、DNS 和路由',lambda:check(cfg,self.stop),self.show_report)

    def show_report(self,report):
        old=self.report;changes=[];notices=[]
        if old and fingerprint(old)!=fingerprint(report):
            self.invalidate('网络、节点或路由已变化')
            if old['wlan']['gateway']!=report['wlan']['gateway']:
                notices.append('WLAN 网关已变化，现有节点路由需要更新。');changes.append(('change.gateway','WLAN 网关变化',notices[-1]))
            if old['node']!=report['node']:
                notices.append('节点配置已变化，请核对并更新对应目标路由。');changes.append(('change.node','节点配置变化',notices[-1]))
            added=set(report['addresses'])-set(old['addresses']);gone=set(old['addresses'])-set(report['addresses'])
            if added or gone:
                notices.append('解析变化：新增 '+(', '.join(sorted(added)) or '无')+'；失效 '+(', '.join(sorted(gone)) or '无')+'。旧路由仅可在管理范围内清理。')
                changes.append(('change.dns','节点解析地址变化',notices[-1]))
        self.report=report;self.last_check=time.monotonic()
        self.combo.blockSignals(True);self.combo.clear();self.combo.addItems([n['tag'] for n in report['nodes']] or ['未识别出站'])
        node=report['node']
        if node and not self.manual.isChecked():
            self.combo.setCurrentText(node['tag']);self.host.setText(node['host']);self.port.setValue(node['port'])
            self.protocol.setText(node['protocol']);self.transport.setCurrentText(node['transport'])
        self.combo.blockSignals(False)
        wlan=report['wlan'];self.wlan_title.setText(self.config['wlan']+'  /  '+('已连接' if wlan['connected'] else '已断开'))
        set_color(self.wlan_title,GREEN if wlan['connected'] else RED,16,True)
        self.network_text.setText(f'IPv4  {", ".join(wlan["ipv4"]) or "无"}    ·    接口 #{wlan["index"]}\n网关  {wlan["gateway"] or "缺失"}')
        self.company_title.setText(self.config['company']+'  /  '+('在线' if report['company'] else '未连接'))
        default=report['defaults'][0]['alias'] if report['defaults'] else '无'
        self.default_label.setText('普通默认路由  '+default+(' · 公司连接未在线' if not report['company'] else ''))
        self.listener_label.setText('127.0.0.1:10808  /  '+(f'监听中 · PID {report["listener"]["pid"]}' if report['listener'] else '未监听'))
        set_color(self.listener_label,GREEN if report['listener'] else RED,12)
        good=bool(report['rows']) and all(r['ok'] for r in report['rows']) and not report['dns_error'] and wlan['connected']
        via=bool(report['rows']) and all(r['via_wlan'] for r in report['rows'])
        self.route_label.setText('路由分流正常' if good else '专用路由待维护' if via else '路由异常 / 待检查')
        set_color(self.route_label,GREEN if good else AMBER if via else RED,24,True)
        detail='节点经 WLAN · 专用路由与网关一致' if good else '选路经 WLAN，请核对专用路由和网关' if via else '请检查网络连接、节点和系统选路'
        self.route_detail.setText(detail+'\n'+report['time']);self.route_count.setText(f'{len(report["rows"])} 个目标 / IPv4 + IPv6')
        self.table.set_rows(report['rows'])
        hints=list(report['warnings'])+([node['warning']] if node and node['warning'] else [])
        self.node_hint.setText('解析地址  '+(', '.join(report['addresses']) or '未解析')+
            ('  |  '+'；'.join(hints) if hints else '')+('  |  '+report['dns_error'] if report['dns_error'] else ''))
        set_color(self.node_hint,AMBER if hints or report['dns_error'] else MUTED,12)
        self.notice.setText(' '.join(notices) if notices else '；'.join(report['faults']) if report['faults'] else '路由检查已完成。按系统当前选路，节点连接经过 WLAN。')
        set_color(self.notice,AMBER if notices else RED if report['faults'] else MUTED,13)
        self.notify_faults(events=changes)
        self.log.info('检查 WLAN=%s idx=%s gateway=%s company=%s targets=%s faults=%s',wlan['connected'],wlan['index'],wlan['gateway'],report['company'],report['addresses'],report['faults'])

    def notify_faults(self,*,events=(),automatic=True):
        self.notifications.update(fault_snapshot(self.report,self.proxy),events=events,
            unconfirmed=('proxy_https',) if self.proxy is None else (),automatic=automatic and self.can_notify())

    def can_notify(self):return self.close_prompt is None and QApplication.activeModalWidget() is None

    def _send_tray_reminder(self,title,text):
        if self.tray is not None and self.tray.supportsMessages():self.tray.showMessage(title,text,QSystemTrayIcon.MessageIcon.Warning,10000);return True
        return False

    def update_notification_badge(self):
        state=self.notifications.state;text='提醒摘要'
        if state.unread_count:text+=f' · {state.unread_count} 未读'
        elif state.active_count:text+=f' · {state.active_count} 异常'
        self.notification_button.setText(text)

    def show_notifications(self):
        if not self.closing:self.show_window();self.notifications.show_details()

    def do_proxy(self,*,automatic=False):
        self.task('通过 SOCKS5h 测试 HTTPS',lambda:test_proxy(self.stop),lambda result:self.show_proxy(result,automatic=automatic))

    def show_proxy(self,result,*,automatic=False):
        self.proxy=result;self.last_proxy=time.monotonic()
        self.proxy_label.setText(result['ip'] if result['ok'] else '代理测试失败');set_color(self.proxy_label,'#A7F0DA' if result['ok'] else '#FFC6CC',24,True)
        self.proxy_detail.setText('HTTPS 成功 · '+result['time'][11:19] if result['ok'] else '查看提醒摘要了解原因')
        self.notify_faults(automatic=automatic or result['ok'])
        if not result['ok'] and not automatic and self.can_notify():self.notifications.show_details()
        self.log.info('代理测试 ok=%s ip=%s',result['ok'],result['ip'])

    def auto_gateway(self):
        updated=dict(self.config,gateway='',gateway6='')
        try:save_json(self.data/'settings.json',updated)
        except OSError:self.error('保存失败','无法保存自动网关设置，请检查本机设置目录权限。');return
        self.config=updated
        self.settings_fields['gateway'].setText('');self.settings_fields['gateway6'].setText('')
        self.notice.setText('已切换为实时读取 WLAN 网关；未修改任何路由。');self.do_check()

    def poll(self):
        if self.closing:return
        if self.can_notify():self.notifications.flush()
        if self.busy or not self.monitor.isChecked():return
        if time.monotonic()-self.last_check>=self.interval.value():self.do_check()
        elif self.auto_proxy.isChecked() and time.monotonic()-self.last_proxy>=60:self.do_proxy(automatic=True)

    def track_dialog(self,win):
        self._dialogs=[d for d in self._dialogs if isValid(d)]
        self._dialogs.append(win);win.show();return win

    def error(self,title,text):
        win=QMessageBox(QMessageBox.Icon.Warning,title,text,QMessageBox.StandardButton.Ok,self)
        win.setTextFormat(Qt.TextFormat.PlainText);win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.setWindowModality(Qt.WindowModality.WindowModal);self.track_dialog(win)

    def text_window(self,title,content,apply=None):
        win=dialog(self,title);layout=QVBoxLayout(win);layout.setContentsMargins(24,20,24,20);layout.setSpacing(14)
        layout.addWidget(label(title,23,bold=True));text=text_box();text.setPlainText(content);layout.addWidget(text,1)
        footer=QHBoxLayout();footer.addStretch();footer.addWidget(button('关闭',win.reject))
        if apply is not None:
            def confirm():
                if self.busy or self.closing:return
                win.accept();apply()
            footer.addWidget(button('确认恢复以上路由',confirm,True))
        layout.addLayout(footer);return self.track_dialog(win)

    def prepare_routes(self):
        if self.busy or self.closing:return
        try:cfg=self.collect()
        except (ValueError,OSError) as error:self.error('输入不正确',str(error));return
        def ready(report):self.show_report(report);self.route_dialog(report,cfg)
        self.task('准备路由变更预览',lambda stop,progress:check(cfg,stop,progress),ready,operation=True,cancellable=True)

    def route_dialog(self,report,cfg):
        win=dialog(self,'路由变更预览',1000,700);layout=QVBoxLayout(win);layout.setContentsMargins(24,20,24,20);layout.setSpacing(12)
        layout.addWidget(label('确认路由变更',24,bold=True));layout.addWidget(label('核对目标、网卡、旧/新下一跳及持久化，再决定是否执行。',13,MUTED))
        adopt=QCheckBox('接管本次目标已有的主机静态路由，允许更新旧网关和重复记录')
        cleanup=QCheckBox('清理已失效的旧节点路由，仅限本工具管理范围')
        layout.addWidget(adopt);layout.addWidget(cleanup);text=text_box();layout.addWidget(text,1)
        footer=QHBoxLayout();footer.addStretch();footer.addWidget(button('取消',win.reject))
        current=[None]
        def apply():
            if self.busy or self.closing or current[0] is None:return
            plan=current[0];win.accept();self.apply_plan(plan)
        apply_button=button('确认并应用',apply,True);footer.addWidget(apply_button);layout.addLayout(footer)
        def render():
            try:
                plan=plan_routes(report,cfg,read_json(self.data/'managed.json',[]) or [],adopt.isChecked(),cleanup.isChecked())
                current[0]=plan;text.setPlainText(preview_text(plan));apply_button.setEnabled(True)
                apply_button.setText('确认并应用（管理员）' if plan['creates'] or plan['deletes'] else '核验 / 保存接管选择')
            except Exception as error:current[0]=None;text.setPlainText('无法准备变更\n\n'+str(error));apply_button.setEnabled(False)
        adopt.toggled.connect(render);cleanup.toggled.connect(render);render()
        win.preview=text;win.adopt=adopt;win.cleanup=cleanup;win.apply_button=apply_button
        return self.track_dialog(win)

    def apply_plan(self,plan):
        if self.busy or self.closing:return
        if plan['creates'] or plan['deletes']:
            self.task('应用并核验路由',lambda stop,progress:elevated_job(dict(action='routes',plan=plan),self.stop,progress=progress),self.route_done,operation=True)
        else:self.task('核验现有记录并保存接管选择',lambda stop,progress:execute(plan,stop=stop,progress=progress,
            backup_dir=self.data/'backups',ledger_path=self.data/'managed.json'),self.route_done,operation=True,cancellable=True)

    def route_done(self,result):
        changed=result.get('route_changed',True)
        if changed:self.invalidate('路由操作已完成')
        self.text_window('路由操作结果',result['message']+('\n\n备份：'+result['backup'] if result.get('backup') else ''))
        self.log.info('路由操作 %s backup=%s',result['message'],result.get('backup'))
        self.refresh_backups()
        if changed:self.do_check()
        else:self.last_check=time.monotonic()

    def refresh_backups(self):
        self.backup_list.blockSignals(True);self.backup_list.clear()
        try:paths=sorted((self.data/'backups').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        except OSError:paths=[]
        for path in paths[:200]:
            item=QListWidgetItem(path.name);item.setData(Qt.ItemDataRole.UserRole,str(path));self.backup_list.addItem(item)
        self.backup_list.blockSignals(False)

    def backup_selected(self,current,previous=None):
        if current:self._backup=Path(current.data(Qt.ItemDataRole.UserRole));self.backup_path.setText(str(self._backup))

    def choose_backup(self):
        chosen,_=QFileDialog.getOpenFileName(self,'选择本工具路由备份',str(self.data/'backups'),'路由备份 (*.json)')
        if chosen:self._backup=Path(chosen);self.backup_path.setText(chosen)

    def prepare_restore(self):
        if self.busy or self.closing:return
        if self._backup is None:self.error('尚未选择备份','请先从列表或文件选择器指定本工具的路由备份。');return
        path=self._backup
        try:cfg=self.collect()
        except (ValueError,OSError) as error:self.error('输入不正确',str(error));return
        def ready(report):
            self.show_report(report)
            try:plan=restore_plan(path,report['net']['routes'])
            except Exception as error:self.error('无法恢复',str(error));return
            self.text_window('备份恢复预览',preview_text(plan),lambda:self.apply_plan(plan))
        self.task('核对备份恢复范围',lambda stop,progress:check(cfg,stop,progress),ready,operation=True,cancellable=True)

    def refresh_log(self):
        path=self.data/'diagnostics.log'
        try:
            with path.open('rb') as source:
                source.seek(max(0,path.stat().st_size-100000));text=source.read(100000).decode('utf-8',errors='replace')
        except FileNotFoundError:text='暂无日志'
        except OSError:text='无法读取日志，请检查本机应用数据目录权限。'
        self.log_text.setPlainText(text)

    def reset_settings(self):
        self.runtime_picker.reset(str(self.config.get('runtime','')))
        for key,field in self.settings_fields.items():
            if key=='cooldown':field.setValue(int(self.config[key]))
            else:field.setText(str(self.config.get(key,'')))
        self.close_action_menu.setCurrentText(next((name for name,value in CLOSE_CHOICES.items() if value==self.config.get('close_action')),'每次询问'))
        self.settings_hint.setText('设置已载入，修改先保留为草稿。')

    def save_settings(self):
        if self.busy or self.closing:return
        try:
            changes={key:field.value() if key=='cooldown' else field.text().strip() for key,field in self.settings_fields.items()}
            if not changes['wlan'] or not changes['company']:raise ValueError('请填写无线网卡和公司连接名称。')
            for key in ('gateway','gateway6'):
                if changes[key]:
                    address=ipaddress.ip_address(changes[key])
                    if address.is_unspecified or address.is_multicast or address.version!=(6 if key=='gateway6' else 4):raise ValueError('网关地址不正确')
            runtime=self.runtime_picker.path.text().strip()
            changes.update(runtime=str(Path(os.path.expandvars(runtime)).expanduser().resolve()) if runtime else '',
                           close_action=CLOSE_CHOICES[self.close_action_menu.currentText()])
            updated=dict(self.config,**changes);save_json(self.data/'settings.json',updated)
        except (ValueError,OSError) as error:self.error('设置不正确',str(error));return
        self.config=updated;self.notifications.state.cooldown=updated['cooldown'];self.settings_hint.setText('设置已保存。未修改任何路由。')
        self.invalidate('设置已变化');self.do_check()

    def about(self):
        from PySide6.QtCore import qVersion
        text=f'v2rayN 分流助手 {VERSION}\n\n界面：PySide6 / Qt Widgets {qVersion()}\nPython 网络诊断与路由维护工具。\n\n使用 Qt / PySide6 社区版组件（LGPLv3 等许可），动态链接；组件原始许可文本、对应源代码获取及替换重建说明随分发包提供。\n图标：Microsoft Fluent System Icons（MIT）。\n\n配置和备份保存在本机应用数据目录，分享前请核对诊断信息。'
        self.text_window('关于与组件许可',text)

    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():self.log.warning('托盘不可用，最小化使用任务栏');return
        self.tray=QSystemTrayIcon(QIcon(str(icon_path())),self);self.tray.setToolTip('v2rayN 分流助手')
        menu=QMenu(self)
        for name,handler in [('显示窗口',self.show_window),('查看提醒摘要',self.show_notifications),('立即检查',self.do_check),('退出',self.quit)]:menu.addAction(name,handler)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason:self.show_window() if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,QSystemTrayIcon.ActivationReason.Trigger) else None)
        self.tray.messageClicked.connect(self.show_notifications);self.tray.show()

    def minimize(self):
        self.dismiss_close_prompt()
        if self.tray is not None:self.hide()
        else:self.showMinimized()

    def show_window(self):
        if self.closing:return
        self.showNormal();self.raise_();self.activateWindow()
        if self.close_prompt is not None:self.close_prompt.raise_();self.close_prompt.activateWindow()

    def closeEvent(self,event):
        if self._allow_close:event.accept()
        else:event.ignore();self.request_close()

    def request_close(self):
        if self.closing:return
        if self.close_prompt is not None:self.close_prompt.raise_();self.close_prompt.activateWindow();return
        modal=QApplication.activeModalWidget()
        if modal is not None:modal.raise_();modal.activateWindow();return
        action=self.config.get('close_action','ask')
        if action=='exit':self.quit();return
        if action=='tray':self.minimize();return
        self.close_prompt=ClosePrompt(self,confirm=self.confirm_close,cancel=self.dismiss_close_prompt,has_tray=self.tray is not None)
        self.close_prompt.open()

    def dismiss_close_prompt(self):
        win,self.close_prompt=self.close_prompt,None
        if win is not None and isValid(win):win.blockSignals(True);win.close();win.deleteLater()

    def confirm_close(self,action,remember):
        if self.closing or self.close_prompt is None or action not in ('exit','tray'):return
        if remember:
            updated=dict(self.config,close_action=action)
            try:save_json(self.data/'settings.json',updated)
            except OSError:self.error('无法保存关闭偏好','保存失败。请取消“不再提示”后重试，或检查设置目录权限。');return
            self.config=updated;self.close_action_menu.setCurrentText(next(k for k,v in CLOSE_CHOICES.items() if v==action))
        self.dismiss_close_prompt()
        if action=='exit':self.quit()
        else:self.minimize()

    def quit(self):
        if self.closing:return
        self.closing=True;self.stop.set();self.timer.stop();self.startup_timer.stop();self.runtime_picker.cancel.set()
        self.dismiss_close_prompt();self.notifications.shutdown();self.status.setText('正在停止后台任务并退出…')
        if self._operation is not None:self._operation.stage_label.setText('正在退出，请等待当前任务完成或回滚…')
        for win in self._dialogs:
            if isValid(win):win.blockSignals(True);win.close()
        if not self.busy:self.finish_quit()

    def finish_quit(self):
        if self._destroyed or self.busy:return
        if self.tray is not None:self.tray.hide()
        self._allow_close=True;self._destroyed=True;self.close();self.log.info('程序已正常退出')
        QApplication.instance().quit()


def main():
    app=QApplication.instance() or QApplication([]);configure_application(app)
    window=Application();window.show();app.exec()
