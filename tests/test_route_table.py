from PySide6.QtCore import Qt,QItemSelectionModel
from unittest.mock import patch
from qt_support import QtCase,QAPP


class QtRouteTableTests(QtCase):
    def test_ipv6_complete_values_and_selection_survive_refresh(self):
        table=self.app.table;table.set_rows(self.report['rows']);model=table.model()
        self.assertEqual(model.data(model.index(1,0)),'2001:db8::10')
        table.setCurrentIndex(model.index(1,0));table.set_rows(self.report['rows'])
        self.assertEqual(table.currentIndex().row(),1);self.assertEqual(model.rowCount(),2)

    def test_copy_cells_and_tooltips_escape_markup(self):
        table=self.app.table;self.report['rows'][0]['chosen'][0]['alias']='<img src="file:///private">'
        table.set_rows(self.report['rows']);model=table.model()
        self.assertIn('&lt;img',model.data(model.index(0,1),Qt.ItemDataRole.ToolTipRole))
        table.selectionModel().select(model.index(1,0),QItemSelectionModel.SelectionFlag.Select)
        with patch('guard.route_table.QGuiApplication.clipboard') as clipboard:
            table.copy_selection();clipboard.return_value.setText.assert_called_once_with('2001:db8::10')

    def test_table_scrolling_and_error_color(self):
        rows=[dict(self.report['rows'][0],ip=f'2001:db8::{i}',ok=False) for i in range(30)]
        self.app.table.set_rows(rows);self.app.show();QAPP.processEvents()
        self.assertGreater(self.app.table.verticalScrollBar().maximum(),0)
        self.assertEqual(self.app.table.model().data(self.app.table.model().index(0,0),Qt.ItemDataRole.ForegroundRole).name(),'#b12e40')
