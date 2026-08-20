# lisbon
magnetometer.py

```
class ADS1115_wDRDY
def __init__(self, i2c_bus: int = 1, i2c_addr: int = 0x49, drdy_pin: int = 6, queue_size: int = 100, adc_resolution = "0_512"):

class MagnetometerReader
def __init__(self,pi: pigpio.pi, drdy_pin=25,lis3mdl_addr = 0x1C, adc_addr = 0x49, max_data_points = 128, max_queue=256, magnetometer_resolution = "8", adc_resolution = "0_512"):
```

# lordelo
magnetometer.py

```
class ADS1115_wDRDY
def __init__(self, i2c_bus: int = 1, i2c_addr: int = 0x49, drdy_pin: int = 17, queue_size: int = 100, adc_resolution = "0_512"):

class MagnetometerReader
def __init__(self,pi: pigpio.pi, drdy_pin=6,lis3mdl_addr = 0x1C, adc_addr = 0x49, max_data_points = 128, max_queue=256, magnetometer_resolution = "8", adc_resolution = "0_512"):
```