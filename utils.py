import numpy as np 
from tqdm import tqdm
import pandas as pd
import matplotlib.pyplot as plt
import os
import seaborn as sns
from adafruit_lis3mdl import Range, LIS3MDL

def adc_resolution_to_hex(resolution: str) -> int:
    """
    Convert human-readable ADS1115 full-scale voltage range to config hex.
    Allowed: '0_256', '0_512', '1_024', '2_048', '4_096', '6_144'
    Returns bits to OR into config register
    """
    mapping = {
        "0_256": 0x0000,  # ±0.256 V
        "0_512": 0x0800,  # ±0.512 V
        "1_024": 0x1000,  # ±1.024 V
        "2_048": 0x1800,  # ±2.048 V
        "4_096": 0x2000,  # ±4.096 V
        "6_144": 0x2800,  # ±6.144 V
    }
    if resolution not in mapping:
        raise ValueError(f"Invalid ADC resolution '{resolution}'. Allowed: {list(mapping.keys())}")
    return mapping[resolution]

def adc_resolution_to_vfs(resolution: str) -> float:
    """
    Convert ADC resolution string to full-scale voltage in volts.
    Example: '6_144' -> 6.144
    """
    return float(resolution.replace("_", "."))

def magnetometer_resolution_to_range(resolution: str) -> Range:
    """
    Converts a human-readable resolution string into Adafruit LIS3MDL Range enum.

    Allowed values:
        "4"  -> ±4 Gauss
        "8"  -> ±8 Gauss
        "12" -> ±12 Gauss
        "16" -> ±16 Gauss
    """
    mapping = {
        "4": Range.RANGE_4_GAUSS,
        "8": Range.RANGE_8_GAUSS,
        "12": Range.RANGE_12_GAUSS,
        "16": Range.RANGE_16_GAUSS
    }
    if resolution not in mapping:
        raise ValueError(f"Invalid magnetometer resolution '{resolution}'. Allowed: {list(mapping.keys())}")
    return mapping[resolution]

def angle_to_steps(angle: float) -> int:
    ratio = 475/90
    return int(angle * ratio)

def closed_solver(tt, yy, freq=50):
    tt = np.array(tt)
    yy = np.array(yy)

    w = 2 * np.pi * freq

    cc = np.cos(w * tt)
    ss = np.sin(w * tt)
    ones = np.ones_like(tt)

    X = np.column_stack((ones, cc, ss))

    beta = np.linalg.solve(X.T @ X, X.T @ yy)

    c, a, b = beta

    A = np.sqrt(a**2 + b**2)
    phi = np.arctan2(-b, a)

    res = {
        "amp": A,
        "freq": 50,
        "phase": phi,
        "offset": c,
    }
    res["fitfunc"] = lambda t: A * np.cos(2*np.pi*50*t + phi) + c
    return res

def plot_magnetometer_data(
    data,
    save_dir="./plots",
    filename="magnetic_plot.png"
):
    """
    Processes and plots magnetometer data.

    data: list of tuples (timestamp, mx, my, mz)
    save_dir: directory to save the plot
    filename: file name of the saved plot
    """

    if not data:
        print("No data to plot.")
        return

    # Ensure save directory exists
    os.makedirs(save_dir, exist_ok=True)

    sns.set_theme(style="whitegrid")

    # Convert to DataFrame
    df = pd.DataFrame(data, columns=["timestamp", "mx", "my", "mz", "v_shunt"])
    if len(df) > 1000:
        df = df.iloc[-1000:]

    # Compute relative time
    t0 = df["timestamp"].min()
    df["timestamp_norm"] = df["timestamp"] - t0
    df["diff"]= df["timestamp_norm"].diff().fillna(0)
    df["id"] = range(len(df))
    df["time_mod"] = df["timestamp_norm"].apply(lambda x: x % 0.02)
    
    
    num = 1000
    final_res = {}
    for m_axis in ["mx","my","mz","v_shunt"]:
        final_res[m_axis] = closed_solver(df["timestamp_norm"], df[m_axis])
        print(final_res[m_axis])

    fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)

    for i, axis in enumerate(["mx", "my", "mz", "v_shunt"]):
        ax = axes[i]
        
        # Scatter: time_rel (yellow, high opacity)
        ax.scatter(df["timestamp_norm"], df[axis], color='green', alpha=1, s=50, label='real_samples')
              
        # Fit line (red, semi-transparent)
        t_fit = np.arange(0, 1, 0.001)
        ax.plot(t_fit, final_res[axis]["fitfunc"](t_fit), color='red', alpha=0.7, label='fit')
        
        # Set labels, title, grid
        ax.set_xlabel('Time [s]')
        if axis == "v_shunt":
            ax.set_ylabel(f"{axis[-1].upper()} (V)")
        else:
            ax.set_ylabel(f"{axis[-1].upper()} (uT)")
        ax.set_title('Sensor Sampling a 50Hz Signal at 155Hz')
        ax.grid(True)
        ax.legend()
        ax.set_xlim(0, 0.06)

    axes[-1].set_xlabel("Time (s)")
    plt.tight_layout()

    # Save or show
    full_path = os.path.join(save_dir, filename)
    fig.savefig(full_path)

    df.to_csv(save_dir+"/data_{}.csv".format(filename))
    print(f"Plot saved to {full_path}")
    return df