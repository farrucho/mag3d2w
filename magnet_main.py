import argparse
import subprocess
import time
import pigpio
import pandas as pd

from .magnetometer import MagnetometerReader
from .motor import StepperMotor
from .relay import RelayController
from .utils import angle_to_steps, plot_magnetometer_data

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

    args = parser.parse_args()

    if args.num_points < 2:
        parser.error("--num-points must be >= 2")



    # -------------------------------------------------------------
    # 1. Caso: Ângulo == 0° (Espira Horizontal - Passa por baixo)
    # -------------------------------------------------------------
    # if args.coil_angle == 0:
    #     if args.start_position < 0 or args.start_position > 3500:
    #         parser.error("--start_position must be between 0 and 3500 when coil angle is 0")
    #     if args.max_position < 0 or args.max_position > 3500:
    #         parser.error("--max_position must be between 0 and 3500 when coil angle is 0")

    # # -------------------------------------------------------------
    # # 2. Caso: 0° < Ângulo <= 75° (Limites padrão != 0 -> >= 847 passos)
    # # -------------------------------------------------------------
    # elif 0 < args.coil_angle <= 75:
    #     if args.start_position < 847 or args.start_position > 3500:
    #         parser.error("--start_position must be between 847 and 3500 for coil angle between 0° and 75°")
    #     if args.max_position < 847 or args.max_position > 3500:
    #         parser.error("--max_position must be between 847 and 3500 for coil angle between 0° and 75°")

    # # -------------------------------------------------------------
    # # 3. Caso: 75° < Ângulo <= 120° (35 mm -> >= 758 passos)
    # # -------------------------------------------------------------
    # elif 75 < args.coil_angle <= 120:
    #     min_steps_closer = 758  # 35 mm (~758 passos)
    #     if args.start_position < min_steps_closer or args.start_position > 3500:
    #         parser.error(f"--start_position must be between {min_steps_closer} and 3500 for coil angle between 75° and 120°")
    #     if args.max_position < min_steps_closer or args.max_position > 3500:
    #         parser.error(f"--max_position must be between {min_steps_closer} and 3500 for coil angle between 75° and 120°")

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
    reader = None

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
        if args.coil_angle != 0:
            print(f"Rodando espira para {args.coil_angle}°...")
            coil.move_steps(angle_to_steps(args.coil_angle), "backward")
            time.sleep(0.3)

        # Move o carrinho dos 60 mm para a posição inicial pedida pelo utilizador
        delta_to_start = args.start_position - safe_standoff_steps
        if delta_to_start > 0:
            motor.move_steps(delta_to_start, "backward")
        elif delta_to_start < 0:
            motor.move_steps(abs(delta_to_start), "forward")
        time.sleep(0.3)

        motor.position = 0
        motor.max_position = args.start_position - args.max_position
        
        step_interval = motor.max_position // (args.num_points - 1)
        print(f"Step interval: {step_interval}")

        data_dict = {}
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

        # =========================================================================
        # 2. TEARDOWN: RETORNO À COORDENADA ABSOLUTA DE 60 MM & ESPIRA A 0°
        # =========================================================================
        print("Finalizando scan: retornando à posição absoluta de 60 mm...")
        current_abs_position = args.start_position - (args.num_points - 1) * step_interval
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

        motor.disable()
        coil.disable()
        reader.stop()
        relay.off()
        start_positions = [i * step_interval for i in range(args.num_points)]
        return_data = {}
        for j, data in data_dict.items():
            df = pd.DataFrame(data, columns=["timestamp", "mx", "my", "mz", "v_shunt"])
            return_data[start_positions[j]] = df
        print("Scan complete!")
    except KeyboardInterrupt:
        print("Interrupted by user")

        try:
            coil.find_max()
        except Exception:
            pass

        if reader:
            data = reader.get_data_copy()
            plot_magnetometer_data(data=data)
            reader.stop()

        motor.disable()
        coil.disable()
        relay.off()

    except Exception as e:
        print(f"Error: {e}")

        try:
            coil.find_max()
        except Exception:
            pass

        if reader:
            reader.stop()

        motor.disable()
        coil.disable()
        relay.off()
        raise

    finally:
        pi.stop()
        stop_pigpiod()
    return return_data


# =========================
# Entry Point
# =========================
if __name__ == "__main__":
    main()