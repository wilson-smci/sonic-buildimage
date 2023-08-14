#!/usr/bin/env python

########################################################################
#
# DELLEMC E3224F
#
# Abstract base class for implementing a platform-specific class with
# which to interact with a hardware watchdog module in SONiC
#
########################################################################

try:
    import ctypes
    from sonic_platform_base.watchdog_base import WatchdogBase
except ImportError as e:
    raise ImportError(str(e) + "- required module not found")


class _timespec(ctypes.Structure):
    _fields_ = [
            ('tv_sec', ctypes.c_long),
            ('tv_nsec', ctypes.c_long)
    ]


class Watchdog(WatchdogBase):
    """
    Abstract base class for interfacing with a hardware watchdog module
    """

    TIMERS = [15,20,30,40,50,60,65,70,80,100,120,140,160,180,210,240]

    armed_time = 0
    timeout = 0
    CLOCK_MONOTONIC = 1

    def __init__(self):
        WatchdogBase.__init__(self)
        self._librt = ctypes.CDLL('librt.so.1', use_errno=True)
        self._clock_gettime = self._librt.clock_gettime
        self._clock_gettime.argtypes=[ctypes.c_int, ctypes.POINTER(_timespec)]
        self.watchdog_reg = "watchdog"

    def _get_cpld_register(self, reg_name):
        # On successful read, returns the value read from given
        # reg name and on failure rethrns 'ERR'
        cpld_dir = "/sys/devices/platform/dell-e3224f-cpld.0/"
        cpld_reg_file = cpld_dir + '/' + reg_name
        try:
            with open(cpld_reg_file, 'r') as fd:
                rv = fd.read()
        except IOError : return 'ERR'
        return rv.strip('\r\n').lstrip(' ')

    def _set_cpld_register(self, reg_name, value):
        # On successful write, returns the value will be written on
        # reg_name and on failure returns 'ERR'

        cpld_dir = "/sys/devices/platform/dell-e3224f-cpld.0/"
        cpld_reg_file = cpld_dir + '/' + reg_name

        try:
           with open(cpld_reg_file, 'w') as fd:
                rv = fd.write(str(value))
        except Exception:
            rv = 'ERR'

        return rv

    def _get_reg_val(self):
        value = self._get_cpld_register(self.watchdog_reg).strip()
        if value == 'ERR': return False

        return int(value,16)

    def _set_reg_val(self,val):
        value = self._set_cpld_register(self.watchdog_reg, val)
        return value

    def _get_time(self):
        """
        To get clock monotonic time
        """
        ts = _timespec()
        if self._clock_gettime(self.CLOCK_MONOTONIC, ctypes.pointer(ts)) != 0:
            self._errno = ctypes.get_errno()
            return 0
        return ts.tv_sec + ts.tv_nsec * 1e-9

    def arm(self, seconds):
        """
        Arm the hardware watchdog with a timeout of <seconds> seconds.
        If the watchdog is currently armed, calling this function will
        simply reset the timer to the provided value. If the underlying
        hardware does not support the value provided in <seconds>, this
        method should arm the watchdog with the *next greater*
        available value.

        Returns:
            An integer specifying the *actual* number of seconds the
            watchdog was armed with. On failure returns -1.
        """
        timer_offset = -1
        for key,timer_seconds in enumerate(self.TIMERS):
            if seconds > 0 and seconds <= timer_seconds:
                timer_offset = key
                seconds = timer_seconds
                break

        if timer_offset == -1:
            return -1

        # Extracting 5th to 8th bits for WD timer values
        reg_val = self._get_reg_val()
        wd_timer_offset = (reg_val >> 4) & 0xF

        if wd_timer_offset != timer_offset:
            # Setting 5th to 8th bits
            # value from timer_offset
            self.disarm()
            self._set_reg_val((reg_val & 0x0F) | (timer_offset << 4))

        if self.is_armed():
            # Setting last bit to WD Timer punch
            # Last bit = WD Timer punch
            self._set_reg_val(reg_val & 0xFE)

        else:
            # Setting 4th bit to enable WD
            # 4th bit = Enable WD
            reg_val = self._get_reg_val()
            self._set_reg_val(reg_val | 0x8)

        self.armed_time = self._get_time()
        self.timeout = seconds
        return seconds

    def disarm(self):
        """
        Disarm the hardware watchdog

        Returns:
            A boolean, True if watchdog is disarmed successfully, False
            if not
        """
        if self.is_armed():
            # Setting 4th bit to disable WD
            # 4th bit = Disable WD
            reg_val = self._get_reg_val()
            self._set_reg_val(reg_val & 0xF7)

            self.armed_time = 0
            self.timeout = 0
            return True

        return False

    def is_armed(self):
        """
        Retrieves the armed state of the hardware watchdog.

        Returns:
            A boolean, True if watchdog is armed, False if not
        """

        # Extracting 4th bit to get WD Enable/Disable status
        # 0 - Disabled WD
        # 1 - Enabled WD
        reg_val = self._get_reg_val()
        wd_offset = (reg_val >> 3) & 1

        return bool(wd_offset)

    def get_remaining_time(self):
        """
        If the watchdog is armed, retrieve the number of seconds
        remaining on the watchdog timer

        Returns:
            An integer specifying the number of seconds remaining on
            their watchdog timer. If the watchdog is not armed, returns
            -1.

            E3224F doesnot have hardware support to show remaining time.
            Due to this limitation, this API is implemented in software.
            This API would return correct software time difference if it
            is called from the process which armed the watchdog timer.
            If this API called from any other process, it would return
            0. If the watchdog is not armed, this API would return -1.
        """
        if not self.is_armed():
            return -1

        if self.armed_time > 0 and self.timeout != 0:
            cur_time = self._get_time()

            if cur_time <= 0:
                return 0

            diff_time = int(cur_time - self.armed_time)

            if diff_time > self.timeout:
                return self.timeout
            else:
                return self.timeout - diff_time

        return 0
