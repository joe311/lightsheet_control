import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore
from superqt import QLabeledDoubleRangeSlider, QLabeledDoubleSlider, QLabeledSlider
from skimage import io
import nidaqmx

from waveformgen import WaveformGen


class WaveformGUI(QtWidgets.QWidget):
    def __init__(self, devname='auto', sample_rate=100000):
        if devname == 'auto':  # Take the first attached/running NI box
            devname = nidaqmx.system.System.local().devices.device_names[0]

        super(WaveformGUI, self).__init__()
        self.sample_rate = sample_rate
        self.wavegen = WaveformGen(devname=devname, sample_rate=self.sample_rate)

        # Build the QT gui elements
        self.setWindowTitle('Galvo control')
        self.setMinimumSize(1000, 800)

        hbox = QtWidgets.QHBoxLayout()
        self.setLayout(hbox)

        def slider_label(text):
            """Helper function for making slider labels"""
            label = QtWidgets.QLabel(text, self)
            label.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
            label.setMinimumWidth(80)
            return label

        vbox_control = QtWidgets.QVBoxLayout()
        hbox.addLayout(vbox_control)
        hbox.addSpacing(10)
        # vbox_control.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Fixed)
        # vbox_control.setSizeConstraint(500)

        self.startstopbutton = QtWidgets.QPushButton("Start")
        self.startstopbutton.setFixedHeight(85)
        vbox_control.addWidget(self.startstopbutton)
        vbox_control.addSpacing(10)
        # self.startstopbutton.setMaximumWidth(300)

        self.zerobutton = QtWidgets.QPushButton("Zero galvos")
        self.zerobutton.setFixedHeight(45)
        vbox_control.addWidget(self.zerobutton)
        vbox_control.addSpacing(15)
        # self.zerobutton.setMaximumWidth(300)

        self.x = QLabeledDoubleRangeSlider(QtCore.Qt.Horizontal)
        self.x.setRange(self.wavegen.xgalvo.min_val, self.wavegen.xgalvo.max_val)
        self.x.setValue((-5, 5))
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        vbox_control.addWidget(slider_label("X range (v)"))
        vbox_control.addWidget(self.x)
        vbox_control.addSpacing(8)

        self.z = QLabeledDoubleRangeSlider(QtCore.Qt.Horizontal)
        self.z.setRange(self.wavegen.zgalvo.min_val, self.wavegen.zgalvo.max_val)
        self.z.setValue((-5, 5))
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        vbox_control.addWidget(slider_label("Z range (v)"))
        vbox_control.addWidget(self.z)
        vbox_control.addSpacing(8)

        self.piezo = QLabeledDoubleRangeSlider(QtCore.Qt.Horizontal)
        self.piezo.setRange(self.wavegen.piezowaveform.min_val, self.wavegen.piezowaveform.max_val)
        self.piezo.setValue((0, 5))
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        vbox_control.addWidget(slider_label("Piezo range (v)"))
        vbox_control.addWidget(self.piezo)
        vbox_control.addSpacing(8)

        # self.fps = QtWidgets.QLabel()
        # self.fps.setText("Frames per second: ?")
        # vbox_control.addWidget(self.fps)
        # vbox_control.addSpacing(10)

        vbox_images = QtWidgets.QVBoxLayout()
        hbox.addLayout(vbox_images)
        graphics = pg.ImageView()  # QtWidgets.QGraphicsView()
        graphics.show()
        graphics.setImage(np.random.random((200, 100)))
        # self.wavegen.reading_image_callback = lambda x: graphics.setImage(x, autoLevels=False, autoHistogramRange=False, levelMode='mono')
        graphics.view.setAspectLocked(True)
        # graphics.view.setRange(xRange=[0, 100], yRange=[0, 100], padding=0)
        graphics.ui.roiBtn.hide()
        graphics.ui.menuBtn.hide()
        graphics.getHistogramWidget().setHistogramRange(-20, 20)
        graphics.setLevels(-15, 15)
        graphics.setMinimumWidth(600)
        graphics.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        vbox_images.addWidget(graphics)

        self.savebutton = QtWidgets.QPushButton("Save last acquisition")
        vbox_images.addWidget(self.savebutton)

        # These controls get disabled during scanning
        self.state_toggles_widgets = [self.x, self.z, self.piezo]  # ,self.savebutton]

        # Connect buttons and sliders to the matching functions
        for slider in [self.x, self.z, self.piezo]:
            slider.valueChanged.connect(self.update)
        self.startstopbutton.clicked.connect(self.startstop)
        self.zerobutton.clicked.connect(self.wavegen.zero_output)
        self.savebutton.clicked.connect(self.save)

        self.update()

        self.setGeometry(50, 50, 1400, 1000)
        self.show()
        self.started = False
        self.lastacqframes = []

    def update(self):
        # Give updated values to the wavegen object
        self.wavegen.xgalvo.min, self.wavegen.xgalvo.max = self.x.value()
        self.wavegen.zgalvo.min, self.wavegen.zgalvo.max = self.z.value()
        self.wavegen.piezowaveform.min, self.wavegen.piezowaveform.max = self.piezo.value()

        # self.wavegen.samples_per_pixel = self.samples_per_pixel.value()
        # self.y_pix_lbl.setText(f"# Y Pixels: {self.wavegen.pixels_y}")
        # self.fps.setText(f"Frames per second: {self.wavegen.fps:0.2f}")
        #

    def startstop(self):
        if self.started:
            self.stop()
        else:
            self.start()

    def start(self):
        self.started = True
        self.startstopbutton.setText("Scanning")
        self.startstopbutton.setStyleSheet("background-color: red")
        [w.setDisabled(True) for w in self.state_toggles_widgets]
        self.wavegen.start()

    def stop(self):
        self.started = False
        self.startstopbutton.setText("Start")
        self.startstopbutton.setStyleSheet("")
        [w.setDisabled(False) for w in self.state_toggles_widgets]
        # self.lastacqframes = self.wavegen.frames
        self.wavegen.stop()
        self.wavegen.close()

    # def closeEvent(self, event):
    #     # self.wavegen.close()
    #     event.accept()

    def save(self):
        if self.lastacqframes:
            filename = QtWidgets.QFileDialog.getSaveFileName(filter="Tif files (*.tif)")[0]
            io.imsave(filename, np.stack(self.lastacqframes))
            # msg = QtWidgets.QMessageBox()
            # msg.setIcon(QtWidgets.QMessageBox.Information)
            # msg.setText(f"The last acquisition has been saved to: <b> {filename}</b>")
            # msg.setWindowTitle("Save successful")
            # msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            # msg.exec_()
            print(f"Saved last acq as {filename}")
        else:
            msg = QtWidgets.QMessageBox()
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setText(f"Please acquire data before trying to save!")
            msg.setWindowTitle("No data")
            msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msg.exec_()


if __name__ == '__main__':
    import sys

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('Galvo control')
    wg = WaveformGUI(devname='Dev3')
    sys.exit(app.exec_())
