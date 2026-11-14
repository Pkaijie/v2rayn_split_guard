import logging
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from guard.theme import configure_application
from guard.samples import report_fixture
from guard.ui import Application

QAPP=QApplication.instance() or QApplication([])
configure_application(QAPP)


def pump_until(predicate,timeout=3):
    deadline=time.monotonic()+timeout
    while not predicate():
        QAPP.processEvents();time.sleep(.005)
        if time.monotonic()>deadline:raise AssertionError('Qt event loop did not settle')
    QAPP.processEvents()


class QtCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.data=Path(self.temp.name)
        self.report=report_fixture()
        for replacement in (patch('guard.ui.check',return_value=self.report),
            patch('guard.ui.test_proxy',return_value=dict(ok=True,ip='192.0.2.4',time=self.report['time'],message='模拟成功')),
            patch('guard.ui.elevated_job',side_effect=AssertionError('Real elevation forbidden in UI tests')),
            patch('guard.ui.execute',side_effect=AssertionError('Real route mutation forbidden in UI tests'))):
            replacement.start();self.addCleanup(replacement.stop)
        self.app=Application(data_dir=self.data,autorun=False,tray_enabled=False,logger=logging.getLogger('qt-tests'))
        self.app.monitor.setChecked(False)

    def tearDown(self):
        if not self.app._destroyed:self.app.quit();pump_until(lambda:self.app._destroyed)
        self.app.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);QAPP.processEvents()
