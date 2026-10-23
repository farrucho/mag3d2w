import time
import pigpio

class RelayController:
    def __init__(self, pi, coil_pin=21, voltage_pin=20, led_pin=26):
        self.pi = pi
        self.coil_pin = coil_pin
        self.voltage_pin = voltage_pin
        self.led_pin = led_pin

        self.pi.set_mode(self.coil_pin, pigpio.OUTPUT)
        self.pi.set_mode(self.voltage_pin, pigpio.OUTPUT)
        self.pi.set_mode(self.led_pin, pigpio.OUTPUT)

        self.off()

    def test_coil_on(self):
        self.pi.write(self.coil_pin, 0)
    
    def test_coil_off(self):
        self.pi.write(self.coil_pin, 1)
    
    def test_voltage_12v(self):
        self.pi.write(self.voltage_pin, 0)
    
    def test_voltage_6v(self):
        self.pi.write(self.voltage_pin, 1)
    
    def test_led_on(self):
        self.pi.write(self.led_pin, 0)
    
    def test_led_off(self):
        self.pi.write(self.led_pin, 1)

    def on(self):
        self.pi.write(self.coil_pin, 0)
        self.pi.write(self.led_pin, 0)

    def off(self):
        self.pi.write(self.coil_pin, 1)
        self.pi.write(self.led_pin, 1)

    def set_voltage(self, use_12v: bool):
        self.pi.write(self.voltage_pin, 0 if use_12v else 1)

    def configure(self, relay_on: bool, use_12v: bool):
        self.off()
        time.sleep(0.05)
        self.set_voltage(use_12v)
        time.sleep(0.05)
        if relay_on:
            self.on()
