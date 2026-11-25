import argparse
import math
from fractions import Fraction
import subprocess
import sys
import time
import pigpio
import pandas as pd

from .magnetometer import MagnetometerReader
from .motor import StepperMotor
from .relay import RelayController
from .utils import angle_to_steps, steps_to_angle  # noqa

# CHANGE THIS:
# (BCM GPIO): Lisbon = 6; Lordelo = 25.
ADC_DRDY_PIN = 25

# --- Angle sweep (coil rotates, cart stays at a fixed position) ---------------
ANGLE_SWEEP_MAX_POSITION_STEPS = 3500
ANGLE_SWEEP_MAX_ANGLE = 110


def mm_to_steps(mm):
    """Cart conversion: 0 steps == -59 mm, 1 step == 0.124 mm.
    Rounds UP (away from the coil, the safe side) so the cart is never closer than
    asked: the real position is at most 1 step (0.124 mm) further. Exact arithmetic
    (Fraction), so e.g. 40 mm can't become 798.0000001 -> 799 by float noise."""
    return math.ceil((Fraction(str(mm)) + 59) * 1000 / 124)


# Closest the cart may be (mm) for each range of coil angles. Same rule the web
# page applies (mag3d2w.html, add_relation). (lo, lo_included, hi, hi_included, mm)
CART_MIN_MM_BY_ANGLE = [
    (0,  True,  0,   True,  -59),    # exactly 0 deg
    (0,  False, 75,  False,  40),    # 0 < angle < 75
    (75, True,  90,  True,   15),    # 75 <= angle <= 90
    (90, False, 120, True,   40),    # 90 < angle <= 120
]


def angle_sweep_required_mm(angle_min, angle_max):
    """(required_mm, lo, hi) for the most demanding range of angles the coil goes
    through between angle_min and angle_max (exact interval check, no sampling)."""
    worst = None
    for lo, lo_in, hi, hi_in, mm in CART_MIN_MM_BY_ANGLE:
        a, b = max(angle_min, lo), min(angle_max, hi)
        if a < b:
            touches = True
        elif a == b:                               # a single shared point: must belong to both ranges
            touches = (angle_min <= a <= angle_max) and (a > lo or lo_in) and (a < hi or hi_in)
        else:
            touches = False
        if touches and (worst is None or mm > worst[0]):
            worst = (mm, a, b)
    return worst


def angle_sweep_position_error(angle_min, angle_max, position_steps=None, position_mm=None):
    """None if the fixed cart position is valid for EVERY angle the coil goes
    through between angle_min and angle_max, otherwise a message saying which
    angles make it invalid. Give the position in mm (as typed by the user, exact
    comparison) or in steps (as received by the command line)."""
    worst = angle_sweep_required_mm(angle_min, angle_max)
    if worst is None:
        return None
    required_mm, a, b = worst
    if position_mm is not None:
        invalid, pos_mm = Fraction(str(position_mm)) < required_mm, position_mm
    else:
        invalid = position_steps < mm_to_steps(required_mm)
        pos_mm = round(position_steps * 124 / 1000 - 59, 2)
    if invalid:
        where = f"{a}°" if a == b else f"{a}° to {b}°"
        return (f"cart position {pos_mm} mm is not valid for a coil at {where}: "
                f"it must be >= {required_mm} mm")
    return None

MAG_RES_CHOICES = ["4", "8", "12","16"]
ADC_RES_CHOICES = ["0_256", "0_512", "1_024", "2_048", "4_096", "6_144"]

def coil_angle(value):
    fvalue = float(value)
    if fvalue < 0 or fvalue > 120:
            raise argparse.ArgumentTypeError(f"Coil angle must be between 0 and 120, got {fvalue}")
    return fvalue

def parse_args():
    parser = argparse.ArgumentParser(description="Magnetometer scanning system")

    parser.add_argument("--num_points", type=int, default=10,
                        help="Number of measurement points (>=2)")
    
    parser.add_argument("--num_samples", type=int, default=128,
                        help="Number of measurement samples (<=256)")

    parser.add_argument("--relay_12v", action="store_true",
                        help="Use 12V relay")

    parser.add_argument("--relay_on", action="store_true",
                        help="Enable relay")

    parser.add_argument("--magnetometer_resolution",
                        choices=MAG_RES_CHOICES,
                        default="8")

    parser.add_argument("--adc_resolution",
                        choices=ADC_RES_CHOICES,
                        default="0_512")

    parser.add_argument("--coil_angle", type=coil_angle, default=0,
                        help="Coil angle in degrees. Max 90. Default 0.")
    
    parser.add_argument("--start_position", type=int, default=3000,
                        help="Start position in steps. Default 3000.")
    
    parser.add_argument("--max_position", type=int, default=0,
                        help="Max position in steps. Default 0 switch.")

    parser.add_argument("--sweep", choices=["position", "angle"], default="position",
                        help="position (default): cart moves, coil fixed. "
                             "angle: coil rotates between --angle_min and --angle_max, "
                             "cart stays at --start_position.")

    parser.add_argument("--angle_min", type=float, default=0,
                        help="Angle sweep only: first coil angle in degrees.")

    parser.add_argument("--angle_max", type=float, default=0,
                        help="Angle sweep only: last coil angle in degrees.")

    args = parser.parse_args()

    if args.num_points < 2:
        parser.error("--num-points must be >= 2")

    # Check if arguments are valid
    if args.sweep == "angle":
        if not (0 <= args.angle_min < args.angle_max <= ANGLE_SWEEP_MAX_ANGLE):
            parser.error(f"angle sweep needs 0 <= --angle_min < --angle_max <= {ANGLE_SWEEP_MAX_ANGLE}, "
                         f"got {args.angle_min} and {args.angle_max}")
        if args.start_position > ANGLE_SWEEP_MAX_POSITION_STEPS:
            parser.error(f"angle sweep needs --start_position (fixed cart position) <= "
                         f"{ANGLE_SWEEP_MAX_POSITION_STEPS} steps, got {args.start_position}")
        error = angle_sweep_position_error(args.angle_min, args.angle_max, args.start_position)
        if error:
            parser.error(error)

    return args


# =========================
# pigpio Management
# =========================
def start_pigpiod():
    subprocess.run(["sudo", "pigpiod"], check=True)
    time.sleep(0.5)
    print("pigpiod started")


def stop_pigpiod():
    subprocess.run(["sudo", "killall", "pigpiod"], check=True)
    print("pigpiod stopped")



def main(callback=None):
    args = parse_args()
    reader = motor = coil = relay = None

    start_pigpiod()
    pi = pigpio.pi()

    if not pi.connected:
        raise RuntimeError("Failed to connect to pigpiod")

    try:
        # Initialize hardware
        relay = RelayController(pi)
        relay.configure(args.relay_on, args.relay_12v)

        reader = MagnetometerReader(
            pi=pi,
            drdy_pin=13,
            adc_addr=0x48,
            lis3mdl_addr=0x1C,
            adc_drdy_pin=ADC_DRDY_PIN,
            max_data_points = args.num_samples,
            magnetometer_resolution=args.magnetometer_resolution,
            adc_resolution=args.adc_resolution
        )

        motor = StepperMotor(
            pi=pi,
            pins=[17, 18, 27, 22],
            switch_pin=14,
            max_steps=3500,
            step_delay=0.0012    
        )

        coil = StepperMotor(
            pi=pi,
            pins=[23, 24, 10, 9],
            switch_pin=4,
            step_delay=0.003,
            direction="backward"
        )

        # =========================================================================
        # 1. SETUP: CALIBRAÇÃO NO SWITCH & POSICIONAMENTO SEGURO
        # =========================================================================
        safe_standoff_steps = int((60.0 + 59.0) * 1000 / 124)  # 960 passos (60 mm)

        # Garante que a espira está a 0° (plana)
        print("Homing da espira (0°)...")
        coil.find_max()
        time.sleep(0.3)

        # Calibra o carrinho obrigatoriamente no interruptor de fim-de-curso (origem 0 passos)
        print("Calibrando o carrinho no switch de fim-de-curso (0 passos)...")
        motor.find_max()
        time.sleep(0.3)

        # Afasta o carrinho exatamente para a coordenada segura de 60 mm (960 passos)
        print("Posicionando carrinho a 60 mm de segurança...")
        motor.move_steps(safe_standoff_steps, "backward")
        time.sleep(0.3)

        # Roda a espira para o ângulo pretendido em total segurança
        # (angle sweep: o ângulo inicial é angle_min; a espira roda aqui, com o
        # carrinho ainda nos 60 mm, e só depois o carrinho vai para a posição fixa)
        if args.sweep == "angle":
            initial_angle, initial_steps = args.angle_min, round(args.angle_min * 475 / 90)
        else:
            initial_angle, initial_steps = args.coil_angle, angle_to_steps(args.coil_angle)
        if initial_angle != 0:
            print(f"Rodando espira para {initial_angle}°...")
            coil.move_steps(initial_steps, "backward")
            time.sleep(0.3)

        # Move o carrinho dos 60 mm para a posição inicial pedida pelo utilizador
        delta_to_start = args.start_position - safe_standoff_steps
        if delta_to_start > 0:
            motor.move_steps(delta_to_start, "backward")
        elif delta_to_start < 0:
            motor.move_steps(abs(delta_to_start), "forward")
        time.sleep(0.3)

        data_dict = {}

        if args.sweep == "angle":
            # -----------------------------------------------------------------
            # ANGLE SWEEP: cart parked at args.start_position, coil rotates from
            # angle_min to angle_max in (num_points - 1) equal steps.
            # The coil is already at angle_min (rotated above, cart at 60 mm);
            # coil.position counts coil steps from 0 deg (homed at the start).
            # -----------------------------------------------------------------
            angle_targets = [args.angle_min + k * (args.angle_max - args.angle_min) / (args.num_points - 1)
                             for k in range(args.num_points)]
            step_targets = [round(a * 475 / 90) for a in angle_targets]   # round (not int) so 10° -> 10.04° instead of 9.85°
            print(f"Angle sweep: {args.angle_min}° -> {args.angle_max}° in {args.num_points} points "
                  f"at fixed cart position {args.start_position} steps")

            i = 0
            while i < args.num_points:
                move = step_targets[i] - coil.position
                if move > 0:
                    coil.move_steps(move, "backward")    # backward = angle increases
                elif move < 0:
                    coil.move_steps(abs(move), "forward")
                time.sleep(0.3)

                reader.start()
                data = reader.reset()

                if (not reader.repeat) and (reader.repeat_counter == 1):
                    data_dict[i] = data

                    if callback:
                        # position_steps=0 -> the cart did not move; real angle reached
                        callback(0, data, angle=round(steps_to_angle(coil.position), 2))

                    i += 1
                    reader.repeat_counter = 0

            scan_keys = [steps_to_angle(s) for s in step_targets]
            current_abs_position = args.start_position
        else:
            motor.position = 0
            motor.max_position = args.start_position - args.max_position

            step_interval = motor.max_position // (args.num_points - 1)
            print(f"Step interval: {step_interval}")

            i = 0

            while i < args.num_points:
                target = i * step_interval
                move = target - motor.position

                if move > 0:
                    motor.move_steps(move, "forward")
                elif move < 0:
                    motor.move_steps(abs(move), "backward")

                reader.start()
                data = reader.reset()

                if (not reader.repeat) and (reader.repeat_counter == 1):
                    data_dict[i] = data

                    if callback:
                        callback(motor.position, data)

                    i += 1
                    reader.repeat_counter = 0

            scan_keys = [i * step_interval for i in range(args.num_points)]
            current_abs_position = args.start_position - (args.num_points - 1) * step_interval

        # =========================================================================
        # 2. TEARDOWN: RETORNO À COORDENADA ABSOLUTA DE 60 MM & ESPIRA A 0°
        # =========================================================================
        print("Finalizando scan: retornando à posição absoluta de 60 mm...")
        delta_to_safe = safe_standoff_steps - current_abs_position
        if delta_to_safe > 0:
            motor.move_steps(delta_to_safe, "backward")
        elif delta_to_safe < 0:
            motor.move_steps(abs(delta_to_safe), "forward")
        time.sleep(0.3)

        # Baixa a espira de volta para 0° (plana) com segurança nos 60 mm
        print("Alinhando espira a 0° para a próxima execução...")
        coil.find_max()
        time.sleep(0.3)

        return_data = {}
        for j, data in data_dict.items():
            df = pd.DataFrame(data, columns=["timestamp", "mx", "my", "mz", "v_shunt"])
            return_data[scan_keys[j]] = df
        print("Scan complete!")
    except KeyboardInterrupt:
        print("Interrupted by user")
        raise

    except Exception as e:
        print(f"Error: {e}")

        raise

    finally:
        # Preserve the original error for FREE. Never attempt another homing
        # movement after a failed calibration. Try every cleanup independently.
        failed = sys.exc_info()[0] is not None
        cleanup_error = None
        actions = [(relay.off if relay is not None else None),
                   (motor.disable if motor is not None else None),
                   (coil.disable if coil is not None else None),
                   (reader.stop if reader is not None else None),
                   pi.stop, stop_pigpiod]
        for action in actions:
            if action is not None:
                try:
                    action()
                except Exception as error:
                    print(f"[Cleanup] {getattr(action, '__name__', type(action).__name__)}: {error}")
                    if cleanup_error is None:
                        cleanup_error = error
        if cleanup_error is not None and not failed:
            raise cleanup_error
    return return_data


# =========================
# Entry Point
# =========================
if __name__ == "__main__":
    main()
