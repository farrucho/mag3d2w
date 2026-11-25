import time
import sys
from collections import deque
from mag3d2w import magnet_main
import threading

sent_start = False
data_queue = deque()
experiment_finished = False
experiment_error = None


class AcquisitionError(RuntimeError):
    """Terminal failure; the FREE sender must report status E, not a final result."""
    def __init__(self, cause):
        self.code = getattr(cause, "code", "ACQUISITION_FAILED")
        message = str(cause) or type(cause).__name__
        super().__init__(message if message.startswith(self.code + ":") else f"{self.code}: {message}")

def do_init(config, debug_mode):
    # TODO
    print("[Interface] Initialized with config.")
    return True

def _is_angle_sweep(myjson):
    """The FREE server sends protocol={id,name,config} with every execution."""
    name = str((myjson.get("protocol") or {}).get("name", "")).strip().lower()
    return name == "angle sweep"


def _mm_to_steps(mm):
    # same conversion the position sweep always used (0 steps == -59 mm)
    return int(int(mm + 59) * 1000 / 124)


def do_config(myjson):
    # python main.py --num_points 4 --relay_12v --relay_on --magnetometer_resolution 8 --adc_resolution "0_512" --coil_angle 45 --start_position 3000
    # python main.py --sweep angle --angle_min 10 --angle_max 80 --num_points 15 --start_position 1500 --relay_on
    print(f"[Interface] Configuring device execution with ID: {myjson.get('id')}")

    try:
        cfg = myjson['config']
        sys.argv = ["magnet_main.py"]

        # voltage (common to both protocols)
        if str(cfg["voltage"]) == "6":
            sys.argv.extend(["--relay_on"])
        if str(cfg["voltage"]) == "12":
            sys.argv.extend(["--relay_on"])
            sys.argv.extend(["--relay_12v"])

        # samples taken at each point (common)
        sys.argv.extend(["--num_samples", str(cfg["local_samples"])])

        if _is_angle_sweep(myjson):
            # Angle Sweep: cart parked at `fixed_position`, coil goes angle_min -> angle_max
            sys.argv.extend(["--sweep", "angle"])
            sys.argv.extend(["--angle_min", str(cfg["angle_min"])])
            sys.argv.extend(["--angle_max", str(cfg["angle_max"])])
            sys.argv.extend(["--num_points", str(cfg["n_angle_samples"])])
            fixed_steps = magnet_main.mm_to_steps(cfg["fixed_position"])      # rounds away from the coil, <= 1 step (0.124 mm)
            sys.argv.extend(["--start_position", str(fixed_steps)])
            # refuse right away (status E, nothing moves) if any angle of the sweep makes the position invalid
            error = magnet_main.angle_sweep_position_error(
                float(cfg["angle_min"]), float(cfg["angle_max"]), position_mm=cfg["fixed_position"])
            if error:
                print(f"[Interface] Angle sweep refused: {error}")
                return -1, False
        else:
            # Position Sweep (unchanged behaviour)
            sys.argv.extend(["--coil_angle", str(cfg["angle"])])
            sys.argv.extend(["--num_points", str(cfg["n_pos_samples"])])
            sys.argv.extend(["--start_position", str(_mm_to_steps(cfg["pos_init"]))])
            sys.argv.extend(["--max_position", str(_mm_to_steps(cfg["pos_final"]))])
    except (KeyError, TypeError, ValueError) as e:
        print(f"[Interface] Invalid configuration for this protocol: {e!r}")
        return -1, False

    print(sys.argv)

    return myjson, True




first_timestamp = None

def stream_point_callback(position_steps, data_tuples, angle=None):
    """
    Callback called after each point is measured to stream samples on the line immediately.
    """
    global data_queue, first_timestamp
    try:
        start_position_steps = 0
        if "--start_position" in sys.argv:
            idx = sys.argv.index("--start_position")
            start_position_steps = int(sys.argv[idx + 1])

        total_steps = start_position_steps + abs(position_steps)
        real_pos_mm = round((total_steps * 124 / 1000) - 59, 2)

        if first_timestamp is None and data_tuples:
            first_timestamp = float(data_tuples[0][0])

        for d in data_tuples:
            t, mx, my, mz, v_shunt = d
            data_point = {
                "datetime": float(t) - (first_timestamp if first_timestamp is not None else 0.0),
                "position": real_pos_mm,
                "current": str(float(v_shunt) / 0.1), # Amperes
                "field_x": str(mx),
                "field_y": str(my),
                "field_z": str(mz),
            }
            if angle is not None:
                data_point["angle"] = angle
            data_queue.append(data_point)
    except Exception as e:
        print(f"[Interface] Error in stream_point_callback: {e}")
        raise


def run_hardware_scan():
    """
    Wrapper function that executes main.py's routine and handles
    formatting the output data dictionary into a serial queue.
    """
    global data_queue, experiment_finished, experiment_error, first_timestamp
    try:
        print("[Interface] Launching hardware acquisition")
        first_timestamp = None

        scan_results = magnet_main.main(callback=stream_point_callback)

    except (Exception, KeyboardInterrupt, SystemExit) as e:
        experiment_error = AcquisitionError(e)
        print(f"[Interface] Critical failure during scan execution: {e}")
    finally:
        experiment_finished = True


# def run_hardware_scan():
#     """
#     Execução síncrona original: corre o scan completo até ao fim
#     e só depois despeja todos os dados na fila.
#     """
#     global data_queue, experiment_finished
#     try:
#         print("[Interface] Launching hardware acquisition")

#         # Corre o scan completo sem callback
#         scan_results = magnet_main.main()

#         first_df = next(iter(scan_results.values()))
#         first_timestamp = float(first_df['timestamp'].iloc[0])

#         start_position_steps = 0
#         if "--start_position" in sys.argv:
#             idx = sys.argv.index("--start_position")
#             start_position_steps = int(sys.argv[idx + 1])

#         # Formata e insere todos os pontos na fila de uma só vez
#         for position, df_results in scan_results.items():
#             total_steps = start_position_steps + abs(position)
#             real_pos_mm = round((total_steps * 124 / 1000) - 59, 2)

#             for d in df_results.itertuples():
#                 data_point = {
#                     "datetime": float(d.timestamp) - first_timestamp,
#                     "position": real_pos_mm,
#                     "current": str(float(d.v_shunt) / 0.1), # Amperes
#                     "field_x": str(d.mx),
#                     "field_y": str(d.my),
#                     "field_z": str(d.mz),
#                 }
#                 data_queue.append(data_point)

#     except Exception as e:
#         print(f"[Interface] Critical failure during scan execution: {e}")
#     finally:
#         experiment_finished = True



def do_start():
    global sent_start, experiment_finished, experiment_error, data_queue
    print("[Interface] Resetting streams and preparing transmission sequence.")

    sent_start = False
    experiment_finished = False
    experiment_error = None
    data_queue.clear()

    # Launch hardware acquisition in background so receive_data_from_exp() can run concurrently
    thread = threading.Thread(target=run_hardware_scan, daemon=True)
    thread.start()
    return True

# def do_start():
#     global sent_start, experiment_finished, data_queue
#     print("[Interface] Resetting streams and preparing transmission sequence.")

#     sent_start = False
#     experiment_finished = False
#     data_queue.clear()

#     run_hardware_scan()
#     return True

def receive_data_from_exp():
    global sent_start, experiment_finished, data_queue

    if not sent_start:
        sent_start = True
        return "DATA_START"

    while not data_queue and not experiment_finished:
        time.sleep(1)

    # Never turn an acquisition failure into a successful DATA_END, even
    # when partial samples were queued before the failure.
    if experiment_error is not None:
        raise experiment_error

    if data_queue:
        return data_queue.popleft()

    if experiment_finished and not data_queue:
        return "DATA_END"

    # time.sleep(0.1)
    return None
