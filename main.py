import time
import board
import busio
import adafruit_ssd1306
import rotaryio
from adafruit_onewire.bus import OneWireBus
import os
import wifi
import socketpool
import adafruit_requests
import ssl
import os
import adafruit_ds18x20
from digitalio import DigitalInOut, Direction, Pull
import asyncio
import simpleio
import sdcardio
import storage
import microcontroller
import json

OLED_SDA = board.GP0
OLED_SCL = board.GP1
ROTARY_DT = board.GP2
ROTARY_CLK = board.GP3
ONE_WIRE_PIN = board.GP4
ROTARY_SW = board.GP5
BUZZER = board.GP18
NOTE_G4 = 392
NOTE_C5 = 523

def sec_to_hms(seconds):
    hours = f"{(seconds / 3600):.0f}"
    mins = f"{(seconds / 60 % 60):.0f}"
    secs = f"{(seconds % 60):.0f}"
    millis = f"{(seconds % 1):.3f}".lstrip('0')

    return f"{hours}:{mins}:{secs}{millis}"

def buzz(up=True):
    if up:
        simpleio.tone(BUZZER, NOTE_G4, duration=0.1)
        simpleio.tone(BUZZER, NOTE_C5, duration=0.1)
    else:
        simpleio.tone(BUZZER, NOTE_C5, duration=0.1)
        simpleio.tone(BUZZER, NOTE_G4, duration=0.1)

def init_oled():
    i2c = busio.I2C(scl=OLED_SCL, sda=OLED_SDA, frequency=400_000)
    display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
    display.text("Let's Cook!", 0, 0, 1, size=2)
    display.show()
    time.sleep(1)
    display.fill(0)
    return display

def init_wifi_requests():
    print()
    print("Connecting to WiFi")

    #  connect to your SSID
    wifi.radio.connect(os.getenv('CIRCUITPY_WIFI_SSID'), os.getenv('CIRCUITPY_WIFI_PASSWORD'))
    print("Connected to WiFi")
    pool = socketpool.SocketPool(wifi.radio)
    #  prints MAC address to REPL
    print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])
    #  prints IP address to REPL
    print("My IP address is", wifi.radio.ipv4_address)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    return requests

def init_temp_sensor():
    ow_bus = OneWireBus(ONE_WIRE_PIN)
    devices = ow_bus.scan()
    for device in devices:
        print("ROM = {} \tFamily = 0x{:02x}".format([hex(i) for i in device.rom], device.family_code))

    ds18b20 = adafruit_ds18x20.DS18X20(ow_bus, devices[0])
    ds18b20.resolution = 12
    print('Temperature: {0:0.2f} °C'.format(ds18b20.temperature))
    return ds18b20

def relay_on(requests):
    response = requests.get('http://' + os.getenv('RELAY_IP') + '/cm?cmnd=POWER+ON')
    print(response.text)

def relay_off(requests):
    response = requests.get('http://' + os.getenv('RELAY_IP') + '/cm?cmnd=POWER+OFF')
    print(response.text)

async def read_temperature(state, interval=0.25):
    print('read_temperature')
    ds18b20 = init_temp_sensor()
    while True:
        state.current_temp = ds18b20.temperature # recover from crc error?
        state.dirty = True

        await asyncio.sleep(interval)

async def ui(state, display, interval=0, size=1):
    print('ui')
    while True:
        if state.dirty:
            display.fill(0)
            display.text('tgt:{0:0.2f}c'.format(state.encoder_position), 0, 0, 1, size=size)
            display.text('cur:{0:0.2f}c'.format(state.current_temp), 0, 8 * size, 1, size=size)
            display.text('pid:{0:0.2f}'.format(state.pid_output), 0, 8 * size * 2, 1, size=size)
            line4 = 'relay ' + ("off ", "on ")[state.is_relay_on] if state.running else 'stopped '
            display.text(("_ ", "T ")[state.button] + line4 + state.heartbeat, 0, 8 * size * 3, 1, size=1)

            display.text(f'{sec_to_hms(state.run_time)}', 0, 8 * size * 5, 1, size=size)
            display.text(f'logging to {state.filename}', 0, 8 * size * 6, 1, size=size)
            display.show()

            state.dirty = False

        await asyncio.sleep(interval)

async def rotary_encoder(state, interval=0):
    print('rotary_encoder')
    encoder = rotaryio.IncrementalEncoder(ROTARY_CLK, ROTARY_DT)
    while True:
        state.encoder_position = encoder.position + state.offset
        if state.encoder_last_position is None or state.encoder_position != state.encoder_last_position:
            state.encoder_last_position = state.encoder_position
            state.set_temp = state.encoder_position
            state.dirty = True

        await asyncio.sleep(interval)

async def pid(state, interval=0.25):
    print('pid')
    while True:
        if state.running:
            dt = time.monotonic() - state.last_time
            state.last_time = time.monotonic()

            error = state.set_temp - state.current_temp
            state.integral = state.integral + error * dt
            state.derivative = (error - state.last_error) / dt

            state.last_error = error
            p_term = state.kp * state.last_error
            i_term = state.ki * state.integral
            d_term = state.kd * state.derivative

            output = p_term + i_term + d_term
            state.pid_output = output

            state.dirty = True
        else: # also pause the error correction
            state.last_time = time.monotonic()

        await asyncio.sleep(interval)

async def relay(state, requests, interval=0):
    print('relay')
    relay_off(requests)
    state.is_relay_on = False
    state.dirty = True
    while True:
        if state.running:
            if state.pid_output > 0:
                if(not state.is_relay_on):
                    relay_on(requests)
                    buzz(up=True)
                    state.is_relay_on = True
            else:
                if(state.is_relay_on):
                    buzz(up=False)
                    relay_off(requests)
                    state.is_relay_on = False

            state.dirty = True
        else: # force relay off when stopped
            if(state.is_relay_on):
                buzz(up=False)
                relay_off(requests)
                state.is_relay_on = False

                state.dirty = True

        await asyncio.sleep(interval)

async def rotary_button(state, interval=0):
    print('button')
    btn = DigitalInOut(ROTARY_SW)
    btn.direction = Direction.INPUT
    btn.pull = Pull.UP
    while True:
        cur_state = btn.value
        if cur_state != state.button:
            if (not state.button):
                state.running = not state.running

            print(btn.value)

            state.dirty = True

        state.button = cur_state
        await asyncio.sleep(interval)

async def logger(state, interval=1):
    print('logger')
    files = os.listdir('/sd')
    csv_files = [f for f in files if f.endswith(".csv")]
    print(csv_files)

    names = list(map(lambda f: int(f.split(".")[0]), csv_files))
    if len(csv_files) == 0:
        names = [0]

    last_name = max(names)
    state.filename = str(last_name + 1) + ".csv"
    print(f"logging to {state.filename}")
    with open(f"/sd/{state.filename}", "a") as file:
        file.write(f"{state.csv_headers}\r\n")

    while True:
        if state.running:
            with open(f"/sd/{state.filename}", "a") as file:
                file.write(f"{state.to_csv_line()}\r\n")

        await asyncio.sleep(interval)

async def pulse_heartbeat(state, interval=0):
    print('heartbeat')
    while True:
        if state.running:
            state.heartbeat = ("-", "\\", "|", "/", )[int(time.monotonic()) % 4]
        else:
            state.heartbeat = ("x", "X", "x", "X", )[int(time.monotonic()) % 4]

        state.dirty = True
        await asyncio.sleep(interval)

async def track_run_time(state, interval=0):
    print('run_time')
    while True:
        if state.running:
            state.run_time = time.monotonic() - state.run_time_start
        else:
            state.run_time_start = time.monotonic()

        await asyncio.sleep(interval)

class State:
    DEFAULT_OFFSET = 53
    def __init__(self,
        offset = DEFAULT_OFFSET,
        set_temp = 0,
        current_temp = 0,
        pid_output = 0,
        is_relay_on = False,
        encoder_position = DEFAULT_OFFSET,
        encoder_last_position = None,
        dirty = False,
        last_time = time.monotonic(),
        integral = 0, derivative = 0, last_error = 0,
        kp = 2.0,
        ki = 0.0,
        kd = 0.5,
        button = True,
        running = False,
        heartbeat = "",
        filename = "no sd card",
        run_time = 0,
        run_time_start = time.monotonic(),
    ):

        self.offset = offset
        self.set_temp = set_temp
        self.current_temp = current_temp
        self.pid_output = pid_output
        self.is_relay_on = is_relay_on
        self.encoder_position = encoder_position
        self.encoder_last_position = encoder_last_position
        self.dirty = dirty
        self.last_time = last_time
        self.integral = integral
        self.derivative = derivative
        self.last_error = last_error
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.button = button
        self.running = running
        self.heartbeat = heartbeat
        self.filename = filename
        self.run_time = run_time
        self.run_time_start = run_time_start

    csv_headers = "time,set_temp,current_temp,is_relay_on,pid,error,integral,derivative"
    def to_csv_line(self):
        return f"{self.run_time},{self.set_temp},{self.current_temp},{self.is_relay_on},{self.pid_output},{self.last_error},{self.integral},{self.derivative}"

    def to_json(self):
        return json.dumps(self.__dict__)

    def dump_to_flash(self):
        print("dump")
        print(f"saving state {self.to_json()}")
        # save to flash
        with open("/sd/state.json", "w") as state_file:
            json.dump(self.__dict__, state_file)

    @classmethod
    def load_from_flash(cls):
        # load from flash
        print("load")
        with open("/sd/state.json", "r") as state_file:
            state_json = json.loads(state_file.read())
            return cls(**state_json)

def try_to_recover_from(err, display, requests, state):
    print(err)
    display.fill(0)
    display.text(f"{err}", 0, 0, 1, size=1)
    display.text(f"{type(err)}", 0, 8, 1, size=1)
    display.show()
    relay_off(requests)
    state.offset = state.set_temp
    state.dump_to_flash()
    for _ in range(10):
        buzz(True)

    microcontroller.reset()

async def main():
    spi = busio.SPI(board.GP10, MOSI=board.GP11, MISO=board.GP12)
    cs = board.GP15
    sd = sdcardio.SDCard(spi, cs)
    vfs = storage.VfsFat(sd)
    storage.mount(vfs, '/sd')

    if "state.json" in os.listdir("/sd"):
        print("load state")

        try: # to restore state from flash
            state = State.load_from_flash()
            print(f"loaded state {state.to_json()}")
        except ValueError:
            print("failed to load state")
            state = State()

        os.remove("/sd/state.json")

    else: # if no state, create new state
        print("new state")
        state = State()

    buzz(False)
    buzz(False)
    buzz(True)

    display = init_oled()
    display.fill(0)
    display.text("init WiFi", 0, 0, 1, size=2)
    display.show()

    requests = init_wifi_requests()

    ui_task = asyncio.create_task(ui(state, display))
    temperature_task = asyncio.create_task(read_temperature(state))
    pulse_heartbeat_task = asyncio.create_task(pulse_heartbeat(state))
    encoder_task = asyncio.create_task(rotary_encoder(state))
    pid_task = asyncio.create_task(pid(state))
    logger_task = asyncio.create_task(logger(state))
    rotary_button_task = asyncio.create_task(rotary_button(state))
    track_run_time_task = asyncio.create_task(track_run_time(state))
    relay_task = asyncio.create_task(relay(state, requests))
    print("ready to cook!")

    try:
        await asyncio.gather(
            temperature_task,
            encoder_task,
            pid_task,
            relay_task,
            rotary_button_task,
            logger_task,
            ui_task,
            pulse_heartbeat_task,
            track_run_time_task,
        )
    except Exception as err:
        try_to_recover_from(err, display, requests, state)
        raise err

asyncio.run(main())
