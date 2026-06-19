import pigpio
import time

class StepperMotor:
    def __init__(self, pi: pigpio.pi, pins, switch_pin, step_delay=0.003, max_steps = 2700, direction = "forward"):
        """
        pi          : shared pigpio.pi() instance — pass the same one used
                      by MagnetometerReader so there's only one daemon connection
        pins        : list of 4 BCM GPIO pin numbers for the stepper coils
        switch_pin  : BCM GPIO pin for the limit switch
        step_delay  : seconds between each step in a sequence (default 1ms)
        """
        self.pi = pi
        self.pins = pins
        self.switch_pin = switch_pin
        self.step_delay = step_delay
        self.position = 0
        self.max_position = 0
        self.max_steps = max_steps
        assert direction in ["backward","forward"]
        self.direction = direction
        # Setup motor pins as outputs, all LOW
        for pin in self.pins:
            self.pi.set_mode(pin, pigpio.OUTPUT)
            self.pi.write(pin, 0)

        # Setup limit switch as input with pull-up-
        self.pi.set_mode(self.switch_pin, pigpio.INPUT)
        self.pi.set_pull_up_down(self.switch_pin, pigpio.PUD_UP)

        self.sequence = [
            [1, 0, 0, 0],
            [1, 1, 0, 0],
            [0, 1, 0, 0],
            [0, 1, 1, 0],
            [0, 0, 1, 0],
            [0, 0, 1, 1],
            [0, 0, 0, 1],
            [1, 0, 0, 1],
        ]

    # -------------------- LOW LEVEL --------------------

    def disable(self):
        for pin in self.pins:
            self.pi.write(pin, 0)

    def step_once(self, sequence):
        for step in sequence:
            for pin, value in zip(self.pins, step):
                self.pi.write(pin, value)
            time.sleep(self.step_delay)

    def switch_pressed(self):
        if not self.pi.read(self.switch_pin):
            time.sleep(0.01)  # debounce
            return True
        return False

    # -------------------- MOVEMENT --------------------

    def move_steps(self, steps, direction):
        sequence = list(reversed(self.sequence)) if self.direction == direction else self.sequence
        for _ in range(steps):
            self.step_once(sequence)

        if self.direction == direction:
            self.position += steps
        else:
            self.position -= steps

    # -------------------- HOMING --------------------

    def find_max(self):
        print("Finding max position...")
        steps = 0
        sequence = list(reversed(self.sequence)) if self.direction == "forward" else self.sequence
        while (not self.switch_pressed()) & (steps < self.max_steps):
            self.step_once(sequence)
            steps += 1
        self.disable()
        print(f"Max position: {steps}")

    def go_home(self):
        print("Returning to home...")
        self.move_steps(self.position, "backward")
        self.position = 0
        self.disable()
        print("At home (0)")