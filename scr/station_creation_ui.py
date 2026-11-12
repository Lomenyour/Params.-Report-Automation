"""Create a station and its first turbine without editing the packaged catalogue."""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QMessageBox, QVBoxLayout)
from qt_theme import apply_theme


class StationCreationDialog(QDialog):
    def __init__(self, parent, repository, *, alias='', number=''):
        super().__init__(parent)
        self.repository = repository
        self.created = None
        self.setWindowTitle('Добавить ТЭЦ')
        self.resize(620, 430)
        apply_theme(self)
        layout = QVBoxLayout(self)
        note = QLabel('Укажите станцию и её ГТУ. Паспорт газа можно заполнить после сохранения.',self)
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText('Например: Казанская ТЭЦ-1')
        self.genitive = QLineEdit(self)
        self.genitive.setPlaceholderText('Для Word; если пусто, используется название ТЭЦ')
        self.aliases = QLineEdit(alias,self)
        self.aliases.setPlaceholderText('Например: КазТЭЦ-1; варианты через ;')
        self.company = QComboBox(self)
        self.company.addItem('Не указана','')
        for company_id,name in repository.list_companies():
            self.company.addItem(name,company_id)
        self.number = QLineEdit(number,self)
        self.number.setPlaceholderText('Номер ГТУ, например 1 или 11Б')
        self.model = QLineEdit(self)
        self.model.setPlaceholderText('Модель ГТУ')
        for label,field in (('Название ТЭЦ *',self.name),('Название в род. падеже',self.genitive),
                            ('Варианты имени файла',self.aliases),('Компания',self.company),
                            ('Номер ГТУ *',self.number),('Модель ГТУ *',self.model)):
            field.setAccessibleName(label)
            form.addRow(label,field)
        layout.addLayout(form)
        layout.addWidget(QLabel('* Обязательные поля',self))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel,self)
        buttons.button(QDialogButtonBox.Save).setText('Сохранить')
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus(Qt.OtherFocusReason)

    def accept(self):
        try:
            self.created = self.repository.create_station(self.name.text(),self.number.text(),self.model.text(),
                name_genitive=self.genitive.text(),company_id=self.company.currentData(),
                filename_aliases=[value.strip() for value in re.split(r'[;\n]',self.aliases.text()) if value.strip()])
        except (ValueError,OSError) as error:
            QMessageBox.warning(self,'ТЭЦ не добавлена',str(error))
            return
        super().accept()
