from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QRadioButton,QCheckBox
from .theme import label,button,MUTED,GREEN

CLOSE_CHOICES={'每次询问':'ask','直接退出程序':'exit','最小化到托盘':'tray'}


class ClosePrompt(QDialog):
    def __init__(self,parent,*,confirm,cancel,has_tray):
        super().__init__(parent);self.setWindowTitle('温馨提示');self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(500,320);layout=QVBoxLayout(self);layout.setContentsMargins(28,22,28,22);layout.setSpacing(16)
        heading=label('请选择关闭窗口后的操作',20,bold=True);heading.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(heading)
        layout.addWidget(label('退出将停止后台监测；最小化后继续运行。',13,MUTED))
        choices=QHBoxLayout();self.exit_radio=QRadioButton('直接退出程序');self.tray_radio=QRadioButton('最小化到托盘' if has_tray else '最小化到任务栏')
        self.tray_radio.setChecked(True);choices.addWidget(self.exit_radio);choices.addWidget(self.tray_radio);layout.addLayout(choices)
        self.remember=QCheckBox('不再提示，记住本次选择');layout.addWidget(self.remember)
        controls=QHBoxLayout();self.confirm_button=button('确定',lambda:confirm(self.selected_action(),self.remember.isChecked()),True)
        self.cancel_button=button('取消',self.reject);controls.addWidget(self.confirm_button);controls.addWidget(self.cancel_button);layout.addLayout(controls)
        self.rejected.connect(cancel);self.confirm_button.setDefault(True)

    def selected_action(self):return 'exit' if self.exit_radio.isChecked() else 'tray'
