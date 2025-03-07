""" sensor.py
Sensor Thread
This file in the module will handle the packaging of sensor data
It will be responsible for the GPIO interface with sensor equipment

Git Repo: https://github.com/Lightning-N-a-Bottle/lnb-node
Main Doxygen: https://lightning-n-a-bottle.github.io/lnb-node/docs/html/index.html
Sensor Doxygen: https://lightning-n-a-bottle.github.io/lnb-node/docs/html/namespacenode_1_1sensor.html
"""
import sys
import time

# Circuit Python Imports
import board
import busio
import digitalio
import rtc
from adafruit_datetime import datetime

# Module Constants
from .constants import (GPS, LS, NOISE_FLOOR, SPIKE_REJECT, TUNE_CAP,
                        WATCHDOG_THRESH, NAME)


class Sensor:
    """ Reads the sensors """
    def __init__(self) -> None:
        """ Initializes Sensor Modules connected to the Pico

        RTC needs to be initialized and updated
        GPS only needs to be on until it acquires a fix, then it can be disabled to save power
        and reduce noise.
        The lightning sensor needs to be initialized, calibrated, and configured for interrupts

        Args:
            None
        Returns:
            None
        """
        ### Initialize Modules
        self.clock = rtc.RTC()

        # Setup GPS Module
        self.GPS_ENABLE = digitalio.DigitalInOut(board.GP3)
        self.GPS_ENABLE.direction = digitalio.Direction.OUTPUT
        self.gps_lat, self.gps_long = self.get_GPS_Fix()

        # Generate the filename to append the values to (a new file is generated after each reboot)
        self.filename = f"{NAME}_{time.time()}_({self.gps_lat},{self.gps_long})"

        # Turn off GPS Module after Fix or if disabled in constants.py
        # Sleep required to ensure the GPS value is saved.
        time.sleep(.5)
        self.GPS_ENABLE.value = 0

        # Setup Lightning Sensor Module
        if LS:
            import sparkfun_qwiicas3935  # Lightning Module

            # Set up Interrupt pin on GPIO D21 with a pull-down resistor
            self.as3935_interrupt_pin = digitalio.DigitalInOut(board.GP8)
            self.as3935_interrupt_pin.direction = digitalio.Direction.INPUT
            self.as3935_interrupt_pin.pull = digitalio.Pull.DOWN
            
            # On board LED for lightning detection
            self.PiLED = digitalio.DigitalInOut(board.LED)
            self.PiLED.direction = digitalio.Direction.OUTPUT

            # Create as3935 object
            i2c0 = busio.I2C(board.GP7, board.GP6)  # Create the first I2C interface
            self.as3935 = sparkfun_qwiicas3935.Sparkfun_QwiicAS3935_I2C(i2c0)

            # Check if connected
            if not self.as3935.connected:
                print(f"{__name__}\t| ERROR - Lightning Detector not connected. Please check wiring.")
                sys.exit(1)

            # Set Mode
            self.as3935.indoor_outdoor = self.as3935.OUTDOOR
            afe_mode = self.as3935.indoor_outdoor
            if afe_mode == self.as3935.OUTDOOR:
                print(f"{__name__}\t| DEBUG - The Lightning Detector is in the Outdoor mode.")
            elif afe_mode == self.as3935.INDOOR:
                print(f"{__name__}\t| DEBUG - The Lightning Detector is in the Indoor mode.")
            else:
                print(f"{__name__}\t| DEBUG - The Lightning Detector is in an Unknown mode.")

            # Callibrate - If these parameters should be changed, then do so in constants.py
            self.as3935.noise_level = NOISE_FLOOR
            self.as3935.watchdog_threshold = WATCHDOG_THRESH
            self.as3935.spike_rejection = SPIKE_REJECT
            self.as3935.tune_cap = TUNE_CAP
        else:
            # Set up Interrupt pin on GPIO D21 with a pull-down resistor
            self.as3935_interrupt_pin = digitalio.DigitalInOut(board.GP8)
            self.as3935_interrupt_pin.direction = digitalio.Direction.INPUT
            self.as3935_interrupt_pin.pull = digitalio.Pull.DOWN

    def get_filename(self) -> str:
        """ Getter function for the csv filename

        Args:
            None
        Returns:
            filename (str): formatted name to identify the data from the current session
        """
        return self.filename

    def get_GPS_Fix(self) -> "tuple[float, float]":
        """ Acquire current GPS Fix from the module communicating with satellites

        This function will block until a GPS Fix is acquired, then it will set the rtc value
        and return both the timestamp and the gps coordinates

        Args:
            None
        Returns:

            gps_lat (float): monotonic time value of the fix, used later to name the csv and to 
            gps_long (str): float representing the gps longitude
        TODO: Potentially add a timeout for this feature? Is any data even viable without a GPS Fix/Timestamp update?
        """
        if GPS:
            import adafruit_gps  # GPS Module

            # Enable GPS for collection
            self.GPS_ENABLE.value = 1

            UART = busio.UART(tx=board.GP0, rx=board.GP1, baudrate=9600, timeout=10)
            gps_module = adafruit_gps.GPS(UART, debug=False)    # Use UART/pyserial

            # Turn on the basic GGA and RMC info (what you typically want)
            gps_module.send_command(b"PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0")
            # Set update rate to once a second (1hz) which is what you typically want.
            gps_module.send_command(b"PMTK220,1000")

            # Variable to test whether GPS has a timestamp
            check_y = 2020
            # Wait until the GPS obtains a fix
            while not gps_module.has_fix or check_y == 2020:
                print("Waiting for fix...")
                gps_module.update()                         # Refreshes "has_fix" value
                check_y = gps_module.timestamp_utc.tm_year   # Checks that time has been acquired
                time.sleep(1)
            print(f"{__name__}\t| DEBUG - Got GPS Fix!")

            # Store GPS location
            gps_lat = gps_module.latitude
            gps_long = gps_module.longitude

            # Set RTC using Fix timestamp
            self.clock.datetime = time.struct_time(
                (
                    gps_module.timestamp_utc.tm_year,
                    gps_module.timestamp_utc.tm_mon,
                    gps_module.timestamp_utc.tm_mday,
                    gps_module.timestamp_utc.tm_hour,
                    gps_module.timestamp_utc.tm_min,
                    gps_module.timestamp_utc.tm_sec,
                    gps_module.timestamp_utc.tm_wday,
                    gps_module.timestamp_utc.tm_yday,
                    -1,
                )
            )


        else:
            gps_lat: float = -1
            gps_long: float = -1

        return gps_lat, gps_long

    def timestamp(self) -> str:
        """ Acquire current time from Real Time Clock Module.

        This uses the internal Pico RTC module, but alternatively it can be used with an external
        module if the given microcontroller doesn't have an internal RTC.
        The value stored in this RTC is initialized from the GPS Fix, however if the GPS is
        disabled or disconnected, it will use a default value instead.

        NOTE: If we choose to use a different timestamp value there are 2 options already available:
            - time_int = an integer that represents the amount of time that has passed since Jan 1st, 1970
            - dt* = an object that contains all info about a date object and a time object, can be printed
                *(see https://docs.circuitpython.org/projects/datetime/en/latest/index.html for more info)
            - time_stamp = a utc formatted string that shows a more human-readable version of the time

        UTC - YYYY-MM-DDThh:mm:ssZ
            - sec = epoch % 60
            - min = (epoch // 60) % 60
            - hrs = (epoch // 3600) % 24
            - day = epoch // 86400
        Epoch
            - 1 hour = 3600 seconds
            - 1 day = 86400 seconds
            - 1 week = 604800 seconds
            - 1 month = 2629743 seconds
            - 1 year = 31556929 seconds

        Args:
            None
        Returns:
            time_int (int): amount of seconds that have passed since Jan 1, 1970
                or
            time_stamp (str): utc time formatted in ISO8601 format
        """
        # Acquires the utc formatted time
        dt: datetime = datetime.now()
        time_stamp: str = dt.isoformat(sep="T")

        # time_int: int = time.time()       # DEPRICATED, but still kept for reference

        return time_stamp

    def lightning(self) -> float:
        """ Interacts with the Lightning Sensor Module

        This function will be blocking until the AS3935 measures either a strike or a disturber

        Args:
            None
        Returns:
            distance (float): the distance measured by the lightning sensor, in kilometers
                - [63 if disturber, -1 if disabled]

        GPIO Pins Involved:
        - CS ["Chip Select"]: Pull low to activate SPI reception
        - IRQ ["Interrupt request"]: Triggers when a strike is detected
        - SCL: Clock
        - MISO: Data from AS3935 to microcontroller
        - MOSI: Data from microcontroller to AS3935

        """
        distance = -1

        try:
            i = 0
            while True:
                # When the interrupt goes high
                if self.as3935_interrupt_pin.value:
                    if LS:
                        interrupt_value = self.as3935.read_interrupt_register()

                        # Distance estimation takes into account previous events.
                        distance = self.as3935.distance_to_storm
                        # Energy is a pure number with no physical meaning.
                        intensity = self.as3935.lightning_energy

                        if interrupt_value == self.as3935.NOISE:
                            print(f"{__name__}\t| DEBUG - Noise.")
                            self.as3935.clear_statistics()

                        elif interrupt_value == self.as3935.DISTURBER:
                            i += 1

                            print(f"{__name__}\t| INFO - Disturber {i} detected {distance}km away!")
                            self.as3935.clear_statistics()
                            # Comment out break to not save to csv
                            break

                        elif interrupt_value == self.as3935.LIGHTNING:
                            #Turn on PiLED
                            self.PiLED.value = 1

                            print(f"{__name__}\t| INFO - Lightning strike detected {distance}km away!")
                            self.as3935.clear_statistics()
                            break

                    else:
                        break

                    time.sleep(0.5)
                    self.PiLED.value = 0
        except KeyboardInterrupt:
            pass

        return distance


    def collect(self) -> str:
        """ Collects data from sensors and compiles it into a string

        This thread will handle all communications with the sensors and create new packets
        This function will not return until lightning is actually detected

        Args:
            None
        Returns:
            packet (str): The properly formatted packet to be passed to LoRa
        """
        # When lightning is detected, this will populate the string with the sensor data
        stk: float = self.lightning()     # Acquire Lightning Distance/Intensity
        # Acquire RTC Timestamp, this has to come after the lightning strike
        t_stmp: str = self.timestamp()   # Acquire the UTC formatted timestruct
        # Epoch time, used for graphing data
        t_int: float = time.time()

        # Append to PACKET_QUEUE
        packet: str = f"{t_stmp},{t_int},{self.gps_lat},{self.gps_long},{stk}"
        print(f"{__name__}\t| CREATED={packet}")

        return packet
