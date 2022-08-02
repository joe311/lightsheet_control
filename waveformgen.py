import matplotlib.pyplot as plt
import nidaqmx
import numpy as np
from nidaqmx import stream_readers, stream_writers


class SawtoothWaveform:
    def __init__(self, channel, min_val, max_val):
        self.channel = channel
        self.min_val = min_val
        self.min = min_val
        self.max_val = max_val
        self.max = max_val
        self.frequency = 20

    def waveform(self, sample_times):
        # print(self.channel, self.min, self.max)
        raw = (sample_times * self.frequency) % 1
        scaled = raw * (self.max - self.min) + self.min
        return scaled
        # xraw = ((np.arange(self.samples_per_refresh) + 1) % (self.samples_per_pixel * self.pixels_x)) / (self.samples_per_pixel * self.pixels_x)
        # xraw = np.pad(np.cumsum(gaussian_filter1d(np.diff(xraw), sigma=10)), (1, 0))


class CameraTriggerWaveform:
    def __init__(self, channel, min_val, max_val):
        self.channel = channel
        self.min_val = min_val
        self.min = min_val
        self.max_val = max_val
        self.max = max_val
        self.frequency = 20
        self.duty_cycle = .5

    def waveform(self, sample_times):
        raw = (sample_times * self.frequency - 0.00001) % 1  # tiny offset to start at 0
        raw = (raw < self.duty_cycle).astype(float)
        scaled = raw * (self.max - self.min) + self.min
        return scaled


class WaveformGen:
    def __init__(self, devname='Dev2', sample_rate=10000):
        self.devname = devname
        device = nidaqmx.system.Device(devname)
        print(f"Connecting to {devname}: {device.product_type}")
        assert device.ao_min_rate <= sample_rate <= device.ao_max_rate, "Sample rate exceeded!"
        self.sample_rate = sample_rate

        # self.next_starting_voltage = 0
        # self.last_waveform = None
        self.last_sample_time = 0

        self.refreshes_per_sec = 10  # Hz, approx how often the NI board is serviced
        self.buffer_oversize = 5  # fold, how much bigger is the buffer than one 'refresh' worth
        self.samples_per_refresh = int(self.sample_rate // self.refreshes_per_sec)

        self.framesperbuffer = 4
        print(f"fps: {self.refreshes_per_sec * self.framesperbuffer} ")
        self.bufferspervolume = 5
        self.vps = self.refreshes_per_sec / self.bufferspervolume
        print(f"vps: {self.vps} ")

        self.xgalvo = SawtoothWaveform('/ao0', -10, 10)
        self.zgalvo = SawtoothWaveform('/ao1', -10, 10)
        self.piezowaveform = SawtoothWaveform('/ao2', 0, 10)
        self.camera_trigger = CameraTriggerWaveform('/ao3', 0, 5)
        self._ao_waveforms = [self.xgalvo, self.zgalvo, self.piezowaveform, self.camera_trigger]

        # AI params
        self.ai_channels = ['/ai0']  # Piezo feedback
        self.ai_args = {'min_val': -10,
                        'max_val': 10, 'terminal_config': nidaqmx.constants.TerminalConfiguration.RSE}
        self.reader = None
        self.ai_task = None

        # AO params
        self.writer = None
        self.ao_task = None

        self.counter = 0
        # Could use a clock to drive both tasks, but not sure if helps at all?
        # sample_clk_task = nidaqmx.Task()
        # self.sample_clk_task = sample_clk_task
        # sample_clk_task.co_channels.add_co_pulse_chan_freq(f'{devname}/ctr0', freq=sample_rate)
        # sample_clk_task.timing.cfg_samp_clk_timing(sample_rate, sample_mode=)
        # # sample_clk_task.timing.cfg_implicit_timing(samps_per_chan=nsamples)
        # samp_clk_terminal = f'/{devname}/Ctr0InternalOutput'

        # # write_task.timing.cfg_samp_clk_timing(sample_rate, source=samp_clk_terminal, active_edge=nidaqmx.constants.Edge.RISING, samps_per_chan=nsamples)
        # write_task.timing.cfg_samp_clk_timing(sample_rate, source=samp_clk_terminal, active_edge=nidaqmx.constants.Edge.RISING,
        #                                       sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS, samps_per_chan=bufsize)
        #
        self.update()

    def update(self):  # set proper times
        self.xgalvo.frequency = self.framesperbuffer * self.refreshes_per_sec
        self.zgalvo.frequency = self.vps
        self.piezowaveform.frequency = self.vps
        self.camera_trigger.frequency = self.xgalvo.frequency

    def init_ai(self):
        ai_task = nidaqmx.Task()
        self.ai_task = ai_task
        for ch in self.ai_channels:
            ai_task.ai_channels.add_ai_voltage_chan(self.devname + ch, **self.ai_args)
        self.read_buffer = np.zeros((len(self.ai_channels), self.samples_per_refresh), dtype=np.float64)
        ai_task.timing.cfg_samp_clk_timing(rate=self.sample_rate, sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS)
        # Configure ai to start only once ao is triggered for simultaneous generation and acquisition:
        ai_task.triggers.start_trigger.cfg_dig_edge_start_trig("ao/StartTrigger", trigger_edge=nidaqmx.constants.Edge.RISING)

        ai_task.input_buf_size = self.samples_per_refresh * len(self.ai_channels) * self.buffer_oversize
        self.reader = stream_readers.AnalogMultiChannelReader(ai_task.in_stream)
        self.ai_task.register_every_n_samples_acquired_into_buffer_event(self.samples_per_refresh, self.reading_task_callback)

    def init_ao(self):
        ao_task = nidaqmx.Task()
        self.ao_task = ao_task
        for wave in self._ao_waveforms:
            ao_task.ao_channels.add_ao_voltage_chan(self.devname + wave.channel, min_val=wave.min_val, max_val=wave.max_val)
        ao_task.timing.cfg_samp_clk_timing(rate=self.sample_rate, sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS)
        # Set output buffer to correct size
        ao_task.out_stream.output_buf_size = self.samples_per_refresh * len(self._ao_waveforms) * self.buffer_oversize
        self.writer = stream_writers.AnalogMultiChannelWriter(ao_task.out_stream)
        # fill buffer for first time
        for _ in range(self.buffer_oversize):
            self.writer.write_many_sample(self.waveform())

        self.ao_task.register_every_n_samples_transferred_from_buffer_event(self.samples_per_refresh, self.writing_task_callback)

    def init_tasks(self):
        self.init_ai()
        self.init_ao()

    def start(self):
        if self.ai_task is None or self.ao_task is None:
            self.init_tasks()
        self.ai_task.start()
        self.ao_task.start()

    def stop(self):
        if self.ai_task is not None:
            self.ai_task.stop()
        if self.ao_task is not None:
            self.ao_task.stop()
            self.last_sample_time = 0
            self.counter = 0

    def close(self):
        if self.ai_task is not None:
            self.ai_task.close()
            self.ai_task = None
        if self.ao_task is not None:
            self.ao_task.close()
            self.ao_task = None

    # def __del__(self):
    #     self.close()

    def set_voltages(self, voltages):
        # Voltages - tuple, len channels
        # assert len(voltages) == len(self.ao_channels)

        assert self.ao_task is None, "Can't set voltages when task is active, call .stop first"

        # make temp channel and writer
        with nidaqmx.Task() as temptask:
            for wave in self._ao_waveforms:
                temptask.ao_channels.add_ao_voltage_chan(self.devname + wave.channel, min_val=wave.min_val, max_val=wave.max_val)

            temptask.write(np.asarray(voltages, dtype=np.float64), timeout=2.0, auto_start=True)
            temptask.wait_until_done()
            temptask.stop()

    def zero_output(self):
        self.set_voltages([0, ] * len(self._ao_waveforms))

    def park(self, parkXvolts=8, parkYvolts=8, amp_volts=0):
        self.set_voltages((parkXvolts, parkYvolts, amp_volts))

    def waveform(self):
        # figure out current timebase
        timebase = np.arange(self.samples_per_refresh) / self.sample_rate + self.last_sample_time
        stacked_wave = np.vstack([wave.waveform(timebase) for wave in self._ao_waveforms])
        self.last_sample_time = (self.last_sample_time + 1 / self.refreshes_per_sec) % (1 / self.vps)

        # plt.Figure()
        # for wave in self._ao_waveforms:
        #     plt.plot(wave.waveform(timebase), label=wave.channel)
        # plt.legend()
        # plt.show()
        # print(stacked_wave.shape)
        # shape should be nchannels, nsamples
        return stacked_wave

    def writing_task_callback(self, task_idx, event_type, num_samples, callback_data):
        """This callback is called every time a defined amount of samples have been transferred from the device output
        buffer. This function is registered by register_every_n_samples_transferred_from_buffer_event and it must follow
        prototype defined in nidaqxm documentation.

        Args:
            task_idx (int): Task handle index value
            event_type (nidaqmx.constants.EveryNSamplesEventType): TRANSFERRED_FROM_BUFFER
            num_samples (int): Number of samples that was writen into the write buffer.
            callback_data (object): User data - I use this arg to pass signal generator object.
        """
        data = self.waveform()
        self.writer.write_many_sample(data, timeout=5.0)
        # self.last_waveform = data
        # self.next_starting_voltage = data[0, -1]
        # print('writing')
        self.counter += 1

        # The callback function must return 0 to prevent raising TypeError exception.
        return 0

    def reading_task_callback(self, task_idx, event_type, num_samples, callback_data=None):
        """This callback is called every time a defined amount of samples have been acquired into the input buffer. This
        function is registered by register_every_n_samples_acquired_into_buffer_event and must follow prototype defined
        in nidaqxm documentation.

        Args:
            task_idx (int): Task handle index value
            event_type (nidaqmx.constants.EveryNSamplesEventType): ACQUIRED_INTO_BUFFER
            num_samples (int): Number of samples that were read into the read buffer.
            callback_data (object)[None]: User data can be additionally passed here, if needed.
        """

        self.reader.read_many_sample(self.read_buffer, num_samples, timeout=nidaqmx.constants.WAIT_INFINITELY)
        # print('.', )
        # TODO plot/save read data

        # The callback function must return 0 to prevent raising TypeError exception.
        return 0


if __name__ == '__main__':
    gen = WaveformGen(devname='Dev2')
    gen.start()
    import time

    time.sleep(5)
    gen.close()
    # gen.start()
    # gen.set_voltages((1, 2, 3))
    # gen.start()
    #
    # time.sleep(3)
    # gen.zero_output()
    # time.sleep(3)
    # gen.close()
