"""Asynchronous runtime discovery updates a settings draft, never saved configuration."""
import threading
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QFileDialog
from shiboken6 import isValid
from .discovery import discover_runtime
from .theme import label,button,combo_box,MUTED,AMBER,GREEN,set_color


class StopToken:
    def __init__(self,parent,local):self.parent=parent;self.local=local
    def is_set(self):return self.parent.is_set() or self.local.is_set()


class RuntimeConfigPicker(QWidget):
    def __init__(self,parent,*,start_task,stop):
        super().__init__(parent);self.start_task=start_task;self.stop=stop
        self.generation=0;self.cancel=threading.Event();self.candidates=[]
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        self.path=QLineEdit();self.path.setAccessibleName('运行配置路径');layout.addWidget(self.path)
        controls=QHBoxLayout();self.detect_button=button('自动检测',self.detect);controls.addWidget(self.detect_button)
        controls.addWidget(button('选择配置文件…',self.browse));controls.addStretch();layout.addLayout(controls)
        self.hint=label('检测结果仅填入草稿，保存设置后生效。',12,MUTED);layout.addWidget(self.hint)
        self.options=QWidget();options=QHBoxLayout(self.options);options.setContentsMargins(0,0,0,0)
        self.combo=combo_box();self.combo.currentIndexChanged.connect(self.preview);options.addWidget(self.combo,1)
        options.addWidget(button('采用所选',self.adopt));layout.addWidget(self.options);self.options.hide()

    def reset(self,value):
        self.generation+=1;self.cancel.set();self.path.setText(value);self.options.hide();self.candidates=[]
        self.hint.setText('检测结果仅填入草稿，保存设置后生效。');set_color(self.hint,MUTED,12)

    def browse(self):
        chosen,_=QFileDialog.getOpenFileName(
            self,'选择代理核心运行配置','','运行配置 (*.json *.json5 *.yaml *.yml *.toml);;所有文件 (*)')
        if chosen:self.path.setText(chosen)

    def detect(self):
        original=self.path.text();generation=self.generation
        self.cancel.set();self.cancel=threading.Event();token=StopToken(self.stop,self.cancel)
        self.detect_button.setEnabled(False);self.hint.setText('正在检测运行配置路径…')
        def work():
            try:return discover_runtime(token)
            except Exception:return dict(candidates=[],automatic='',cancelled=False,notes=['检测失败，请手动选择运行配置。'])
        def done(result):
            if not isValid(self):return
            self.detect_button.setEnabled(True)
            if generation!=self.generation or result['cancelled']:return
            self.candidates=result['candidates'];self.notes=' '.join(result['notes'])
            self.combo.blockSignals(True);self.combo.clear()
            for i,candidate in enumerate(self.candidates):self.combo.addItem(f'{i+1} · {candidate["source"]} · PID {candidate["pid"]}')
            self.combo.blockSignals(False);self.options.setVisible(bool(self.candidates))
            if not self.candidates:self.hint.setText(self.notes);set_color(self.hint,AMBER,12)
            elif result['automatic'] and self.path.text()==original:
                self.path.setText(result['automatic']);self.hint.setText('已识别核心加载的配置；保存设置后生效。 '+self.notes);set_color(self.hint,GREEN,12)
            else:self.preview()
        if not self.start_task(work,done):
            self.detect_button.setEnabled(True);self.hint.setText('当前任务尚未完成，请稍后再检测。')

    def selected(self):
        index=self.combo.currentIndex()
        return self.candidates[index] if 0<=index<len(self.candidates) else None

    def preview(self,*args):
        candidate=self.selected()
        if candidate:self.hint.setText('请核对候选后采用：\n'+candidate['path']+'\n'+self.notes);set_color(self.hint,AMBER,12)

    def adopt(self):
        candidate=self.selected()
        if candidate:self.path.setText(candidate['path']);self.hint.setText('已采用候选，保存设置后生效。');set_color(self.hint,MUTED,12)
