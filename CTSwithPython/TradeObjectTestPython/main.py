from PyQt5 import QtWidgets
from MainAppcliaction import MainAppcliaction
import sys

if __name__ == "__main__":

    app = QtWidgets.QApplication(sys.argv)
    MainWindow = MainAppcliaction()
    MainWindow.show()
    sys.exit(app.exec_())