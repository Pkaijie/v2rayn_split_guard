"""Bounded reminder state and a single non-modal summary window."""
from collections import OrderedDict
from dataclasses import dataclass
import time

from .common import timestamp


@dataclass
class Notice:
    key: str
    title: str
    message: str
    kind: str
    status: str
    first_seen: str
    last_seen: str
    count: int = 1
    acknowledged: bool = False


class NotificationState:
    """One unread batch, stable fault keys, and no replay queue."""
    def __init__(self, cooldown=120, *, clock=time.monotonic, stamp=timestamp, limit=50):
        self.cooldown = cooldown
        self.clock, self.stamp, self.limit = clock, stamp, limit
        self.records = OrderedDict()
        self.pending = set()
        self.presented = False
        self.last_delivery = float('-inf')

    @property
    def unread_count(self):
        return sum(not r.acknowledged for r in self.records.values())

    @property
    def active_count(self):
        return sum(r.status == 'active' for r in self.records.values())

    def update_faults(self, faults, unconfirmed=()):
        unconfirmed = set(unconfirmed)
        now = self.stamp()
        for key, record in self.records.items():
            if record.kind != 'fault' or key in faults:
                continue
            if key in unconfirmed:
                if record.status == 'active':
                    record.status, record.last_seen = 'unconfirmed', now
            elif record.status in ('active', 'unconfirmed'):
                record.status, record.last_seen = 'recovered', now
            self.pending.discard(key)
        for key, (title, message) in faults.items():
            record = self.records.get(key)
            if record is None or record.kind != 'fault':
                self.records[key] = Notice(key, title[:100], message[:2000], 'fault', 'active', now, now)
                self.pending.add(key)
            else:
                if record.status == 'recovered':
                    record.acknowledged = False
                    record.first_seen = now
                    self.pending.add(key)
                # Expired proxy evidence becoming a failure again is not proof
                # of recovery/reoccurrence; keep its acknowledgement state.
                record.status, record.last_seen = 'active', now
                record.title, record.message = title[:100], message[:2000]
                record.count += 1
        self._trim()

    def event(self, key, title, message):
        now = self.stamp()
        record = self.records.get(key)
        if record is None:
            self.records[key] = Notice(key, title[:100], message[:2000], 'event', 'event', now, now)
        else:
            record.title, record.message = title[:100], message[:2000]
            record.last_seen, record.acknowledged = now, False
            record.count += 1
        self.pending.add(key)
        self._trim()

    def _trim(self):
        while len(self.records) > self.limit:
            key = next((k for k, r in self.records.items() if r.status != 'active'), next(iter(self.records)))
            del self.records[key]
            self.pending.discard(key)

    def take_notification(self):
        eligible = any(k in self.records and self.records[k].status in ('active', 'event')
                       and not self.records[k].acknowledged for k in self.pending)
        now = self.clock()
        if self.presented or not eligible or now - self.last_delivery < self.cooldown:
            return False
        self.mark_presented()
        return True

    def mark_presented(self):
        self.presented = True
        self.last_delivery = self.clock()
        self.pending.clear()

    def acknowledge(self):
        for record in self.records.values():
            record.acknowledged = True
        self.pending.clear()
        self.presented = False


def fault_snapshot(report, proxy):
    """Group readable diagnostics by stable type, never by changing IP/text."""
    types = (
        ('WLAN 已断开', 'wlan_offline', 'WLAN 已断开'),
        ('WLAN IPv4 网关缺失', 'gateway_missing', 'WLAN 网关缺失'),
        ('未识别代理节点', 'node_missing', '代理节点未确认'),
        ('节点域名解析失败', 'dns_failure', '节点域名解析失败'),
        ('127.0.0.1:10808', 'listener_missing', '代理监听不存在'),
        ('节点选路未经过 WLAN', 'route_not_wlan', '节点选路未经过 WLAN'),
        ('节点专用路由缺失或网关不匹配', 'route_gateway', '节点专用路由待维护'),
    )
    grouped = {}
    for message in (report or {}).get('faults', []):
        key, title = next(((key, title) for prefix, key, title in types if message.startswith(prefix)),
                          ('other_fault', '其他检查异常'))
        grouped.setdefault(key, [title, []])[1].append(message)
    result = {key: (title, '\n'.join(sorted(set(messages)))) for key, (title, messages) in grouped.items()}
    if proxy and not proxy['ok']:
        result['proxy_https'] = ('代理 HTTPS 测试失败', proxy['message'])
    return result


from PySide6.QtCore import QObject,QTimer,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout
from shiboken6 import isValid
from .theme import label,button,text_box,dialog,MUTED


class SummaryDialog(QDialog):
    def __init__(self,parent,closed):
        super().__init__(parent);self.silent=False;self.on_closed=closed
        self.setWindowTitle('提醒摘要');self.resize(840,540);self.rejected.connect(closed)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(12)
        layout.addWidget(label('提醒摘要',23,bold=True))
        self.summary=label('',12,MUTED);layout.addWidget(self.summary)
        self.text=text_box();layout.addWidget(self.text,1)
        layout.addWidget(label('关闭或点击“知道了”后，持续故障不再重复提醒。自动收起保留未读。\n本工具仅提醒，并未阻止任何流量。',12,MUTED))
        layout.addWidget(button('知道了',self.close,True),0,Qt.AlignmentFlag.AlignRight)

    def closeEvent(self,event):
        if not self.silent:self.on_closed()
        event.accept()


class NotificationManager(QObject):
    def __init__(self,root,*,notify,on_change=lambda:None,cooldown=120,
                 clock=time.monotonic,stamp=timestamp,auto_close_ms=20000):
        super().__init__(root);self.root=root;self.notify=notify;self.on_change=on_change
        self.state=NotificationState(cooldown,clock=clock,stamp=stamp)
        self.auto_close_ms=auto_close_ms;self.window=None;self.closed=False;self._rendered=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._auto_hide)

    def update(self,faults,*,events=(),unconfirmed=(),automatic=True):
        if self.closed:return
        self.state.update_faults(faults,unconfirmed)
        for key,title,message in events:self.state.event(key,title,message)
        self._refresh()
        if automatic:self.flush()

    def flush(self):
        if self.closed or not self.state.take_notification():return
        try:
            delivered=bool(self.notify('分流状态提醒',f'{self.state.unread_count} 类未读提醒，{self.state.active_count} 类当前异常。请打开“提醒摘要”查看。'))
        except Exception:delivered=False
        if not delivered:self.show_details(automatic=True)

    def _refresh(self):
        if self.closed:return
        self.on_change()
        if self.window is None:return
        labels={'active':'进行中','recovered':'已恢复','unconfirmed':'待重新测试','event':'配置变化'}
        lines=[]
        for record in sorted(self.state.records.values(),key=lambda r:(r.acknowledged,r.status!='active',r.key)):
            lines.extend([f'{record.title} · {labels[record.status]} · '+('已知晓' if record.acknowledged else '未读'),
                record.message,f'首次：{record.first_seen}  最近：{record.last_seen}  累计检测/更新：{record.count}',''])
        content='\n'.join(lines) if lines else '暂无提醒。后台监测仍按设置运行。'
        self.window.summary.setText(f'{self.state.unread_count} 类未读提醒 · {self.state.active_count} 类当前异常')
        if content!=self._rendered:
            position=self.window.text.verticalScrollBar().value()
            self.window.text.setPlainText(content);self.window.text.verticalScrollBar().setValue(position)
            self._rendered=content

    def show_details(self,*,automatic=False):
        if self.closed:return
        self.state.mark_presented()
        if self.window is None:
            self.window=SummaryDialog(self.root,self._ack_from_close)
            self._rendered=None
        self.timer.stop();self._refresh();self.window.show()
        if automatic:self.timer.start(self.auto_close_ms)
        else:self.window.raise_();self.window.activateWindow()

    def _drop_window(self):
        self.timer.stop();win,self.window=self.window,None;self._rendered=None
        if win is not None and isValid(win):win.silent=True;win.close();win.deleteLater()

    def _ack_from_close(self):
        if not self.closed:self.state.acknowledge()
        self._drop_window();self._refresh()

    def acknowledge(self):
        if not self.closed:self._ack_from_close()

    def _auto_hide(self):self._drop_window()

    def shutdown(self):
        if self.closed:return
        self.closed=True;self._drop_window()
