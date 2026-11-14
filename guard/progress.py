"""One operation window; cancellation is limited to the read-only phase."""
import threading
import time
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QProgressBar
from .theme import label,button,MUTED


class OperationToken:
    def __init__(self,parent):self.parent=parent;self.local=threading.Event()
    def is_set(self):return self.local.is_set() or self.parent.is_set()
    def set(self):self.local.set()
    def wait(self,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        while not self.is_set():
            if deadline is not None and time.monotonic()>=deadline:return False
            self.local.wait(.02 if deadline is None else max(0,min(.02,deadline-time.monotonic())))
        return True


class OperationDialog(QDialog):
    def __init__(self,parent,title,token,cancellable):
        super().__init__(parent);self.setWindowTitle(title);self.setWindowModality(Qt.WindowModality.WindowModal)
        self.token=token;self.cancellable=cancellable;self._finished=False;self.started=time.monotonic()
        work=parent.screen().availableGeometry();self.resize(min(520,int(work.width()*.9)),260)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,22,24,22);layout.setSpacing(16)
        layout.addWidget(label(title,21,bold=True));self.stage_label=label('正在准备…');layout.addWidget(self.stage_label)
        bar=QProgressBar();bar.setRange(0,0);bar.setTextVisible(False);layout.addWidget(bar)
        self.elapsed=label('',12,MUTED);layout.addWidget(self.elapsed)
        self.hint=label('当前为只读检查，可取消。' if cancellable else '本次包含路由变更；请等待完成或回滚，不能强行中断。',12,MUTED)
        layout.addWidget(self.hint);footer=QHBoxLayout();footer.addStretch()
        self.cancel_button=button('取消检查',self.request_cancel);self.cancel_button.setVisible(cancellable);footer.addWidget(self.cancel_button);layout.addLayout(footer)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.tick);self.timer.start();self.tick()

    def tick(self):self.elapsed.setText(f'已用时 {time.monotonic()-self.started:.1f} 秒 · 窗口仍在响应')
    def request_cancel(self):
        if self.cancellable and not self._finished:
            self.token.set();self.cancel_button.setEnabled(False);self.stage_label.setText('正在取消，请等待当前查询结束…')
    def reject(self):self.request_cancel()
    def closeEvent(self,event):
        if self._finished:event.accept()
        else:event.ignore();self.request_cancel()
    def finish(self):
        self._finished=True;self.timer.stop();self.close();self.deleteLater()
