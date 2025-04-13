import time
import spidev
from ADE9000RegMap import *  # Import the register map
from ADE9000API import ADE9000  # Import the ADE9000 class
from ADE9000API_header import *
from ADE9000CalibrationInputs import *
from ADE9000RegMap import *
import inspect
from ADE9000API import *
import requests

import sqlite3
import os


# Server URLs

BASE_URL = "https://edlserver-production.up.railway.app"

# SPI Configuration
SPI_SPEED = 5000000  # 5 MHz
CS_PIN = 8  # Adjust as per your setup
ADE9000_RESET_PIN = 5  # Adjust as per your setup
PM_1 = 4  # PM1 Pin

# Initialize ADE9000
#print(inspect.signature(ADE9000.__init__))
# ade9000 = ADE9000()

# ade9000 = ADE9000(spi_speed=SPI_SPEED, chip_select_pin=CS_PIN)
# ade9000.spi_speed = SPI_SPEED

# def setup():
#     print("Initializing ADE9000...")
#     # Reset ADE9000
#     reset_ade9000()
    
#     # Initialize SPI and ADE9000
#     ade9000.spi_init(spi_speed=SPI_SPEED, chip_select_pin=CS_PIN)
#     ade9000.setup_ADE9000()
    
#     # Read and print RUN register
#     run_register = ade9000.spi_read_16(ADDR_RUN)
#     print(f"RUN Register: {hex(run_register)}")

# def loop():
#     while True:
#         read_register_data()
#         # read_resampled_data()
#         time.sleep(10)

# def read_register_data():
#     print("Reading Register Data...")
    
#     # Read and print AIRMS
#     airms = ade9000.spi_read_32(ADDR_AIRMS)
#     print(f"AIRMS: {hex(airms)}")
    
#     # Read and print Voltage RMS and Active Power
#     data = None
#     vltg_rms_regs = ade9000.read_voltage_rms_regs()
#     power_regs = ade9000.read_active_power_regs()
#     print("multiplying 3.28849*10^-6 for current")
#     print(f"AVRMS: {10.73364*10**(-6)*vltg_rms_regs['VoltageRMSReg_A']}")
#     print(f"AWATT: {4.73755*10**(-3)*power_regs['ActivePowerReg_A']}")

# def read_resampled_data():
#     print("Reading Resampled Data...")
    
#     # Start the Resampling engine
#     ade9000.spi_write_16(ADDR_WFB_CFG, 0x1000)
#     ade9000.spi_write_16(ADDR_WFB_CFG, 0x1010)
#     time.sleep(0.1)  # Wait for buffer to fill
    
#     # Read resampled data
#     resampled_data = ade9000.spi_burst_read_resampled_wfb(0x800, WFB_ELEMENT_ARRAY_SIZE)
    
#     for i in range(len(resampled_data['VA_Resampled'])):
#         print(f"VA: {hex(resampled_data['VA_Resampled'][i])}")
#         print(f"IA: {hex(resampled_data['IA_Resampled'][i])}")
#         print(f"VB: {hex(resampled_data['VB_Resampled'][i])}")
#         print(f"IB: {hex(resampled_data['IB_Resampled'][i])}")
#         print(f"VC: {hex(resampled_data['VC_Resampled'][i])}")
#         print(f"IC: {hex(resampled_data['IC_Resampled'][i])}")
#         print(f"IN: {hex(resampled_data['IN_Resampled'][i])}")

# def reset_ade9000():
#     print("Resetting ADE9000...")
#     # Simulate reset behavior (this should be handled via GPIO)
#     time.sleep(1)
#     print("Reset Done")







####################  changes ..... ##################

DB_PATH = "/home/rpi/Desktop/project/test_server/local_data.db"
def create_local_db():
    """Creates the power_data table in the SQLite database if it doesn't exist."""

    if not os.path.exists(DB_PATH):  # Check if the database file exists
        print(f"[INFO]: Database '{DB_PATH}' not found. Creating a new one.")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS power_data (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            device_id TEXT,
                            phase TEXT,
                            power_watt REAL,
                            power_var REAL,
                            power_va REAL,
                            voltage_rms REAL,
                            current_rms REAL,
                            power_factor REAL,
                            voltage_thd REAL,
                            current_thd REAL,
                            energy_kwh REAL,
                            timestamp INTEGER
                        )''')
    conn.commit()
    conn.close()

def save_to_local_db(data):
    conn = sqlite3.connect("/home/rpi/Desktop/project/test_server/local_data.db")
    cursor = conn.cursor()
    for entry in data:
        cursor.execute('''INSERT INTO power_data (
                            device_id, phase, power_watt, power_var, power_va, 
                            voltage_rms, current_rms, power_factor, voltage_thd, 
                            current_thd, energy_kwh, timestamp)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (entry["device_id"], entry["phase"], entry["power_watt"],
                        entry["power_var"], entry["power_va"], entry["voltage_rms"],
                        entry["current_rms"], entry["power_factor"], entry["voltage_thd"],
                        entry["current_thd"], entry["energy_kwh"], int(time.time())))
    conn.commit()
    conn.close()

def fetch_local_data():
    conn = sqlite3.connect("/home/rpi/Desktop/project/test_server/local_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM power_data")
    data = cursor.fetchall()
    print(data)
    conn.close()
    return data









def data_to_server():


    dummy_power_data = [
    {
        "device_id": "random12",
        "phase": "A",
        "power_watt":55,
        "power_var": 55,
        "power_va": 110.0,
        "voltage_rms": 55,
        "current_rms": 55,
        "power_factor": 0.9,
        "voltage_thd": 0.8,
        "current_thd": 1.2,
        # "timestamp": 1710800000,
        "energy_kwh": 0.0025
    },
    {
        "device_id": "random12",
        "phase": "B",
        "power_watt": 98.7,
        "power_var": 48.3,
        "power_va": 105.2,
        "voltage_rms": 208.9,
        "current_rms": 56,
        "power_factor": 0.88,
        "voltage_thd": 0.9,
        "current_thd": 1.1,
        # "timestamp": 1710800001,
        "energy_kwh": 0.0024
    },
    {
        "device_id": "random12",
        "phase": "C",
        "power_watt": 95.0,
        "power_var": 46.5,
        "power_va": 102.8,
        "voltage_rms": 227.5,
        "current_rms": 0.47,
        "power_factor": 0.87,
        "voltage_thd": 1.0,
        "current_thd": 1.0,
        # "timestamp": 1710800002,
        "energy_kwh": 0.0023
    }
]
    
    device_id = "random12"
    energy_A = 0
    energy_B = 0
    energy_C = 0
    cond = True
    while(cond):
        time.sleep(0.002)
        # Dummy device id, modify as needed

        # reset_ade9000()
        # Initialize SPI and ADE9000
        # ade9000.spi_init(spi_speed=SPI_SPEED, chip_select_pin=CS_PIN)
        # ade9000.setup_ADE9000()

        # # For Phase A
        # power_watt_A = ade9000.read_active_power_regs()["ActivePowerReg_A"]
        # power_var_A = ade9000.read_reactive_power_regs()["ReactivePowerReg_A"]
        # power_va_A = ade9000.read_apparent_power_regs()["ApparentPowerReg_A"]
        # voltage_rms_A = ade9000.read_voltage_rms_regs()["VoltageRMSReg_A"]
        # current_rms_A = ade9000.read_current_rms_regs()["CurrentRMSReg_A"]
        # power_factor_A = ade9000.read_power_factor_regs_values()["PowerFactorValue_A"]
        # voltage_thd_A = ade9000.read_voltage_thd_regs_values()["VoltageTHDValue_A"]
        # current_thd_A = ade9000.read_current_thd_regs_values()["CurrentTHDValue_A"]
        # timestamp_A = int(time.time())  # nanosecond precision timestamp
        # energy_A = power_watt_A/(3.6*10**6)  # Placeholder for energy calculation

        # power_data_dict_A = {
        #     "device_id": device_id,
        #     "phase": "A",
        #     "power_watt": power_watt_A,
        #     "power_var": power_var_A,
        #     "power_va": power_va_A,
        #     "voltage_rms": voltage_rms_A,
        #     "current_rms": current_rms_A,
        #     "power_factor": power_factor_A,
        #     "voltage_thd": voltage_thd_A,
        #     "current_thd": current_thd_A,
        #     "timestamp": timestamp_A,
        #     "energy": energy_A
        # }

        # # For Phase B
        # power_watt_B = ade9000.read_active_power_regs()["ActivePowerReg_B"]
        # power_var_B = ade9000.read_reactive_power_regs()["ReactivePowerReg_B"]
        # power_va_B = ade9000.read_apparent_power_regs()["ApparentPowerReg_B"]
        # voltage_rms_B = ade9000.read_voltage_rms_regs()["VoltageRMSReg_B"]
        # current_rms_B = ade9000.read_current_rms_regs()["CurrentRMSReg_B"]
        # power_factor_B = ade9000.read_power_factor_regs_values()["PowerFactorValue_B"]
        # voltage_thd_B = ade9000.read_voltage_thd_regs_values()["VoltageTHDValue_B"]
        # current_thd_B = ade9000.read_current_thd_regs_values()["CurrentTHDValue_B"]
        # timestamp_B = int(time.time())
        # energy_B = power_watt_B/(3.6*10**6)  # Placeholder

        # power_data_dict_B = {
        #     "device_id": device_id,
        #     "phase": "B",
        #     "power_watt": power_watt_B,
        #     "power_var": power_var_B,
        #     "power_va": power_va_B,
        #     "voltage_rms": voltage_rms_B,
        #     "current_rms": current_rms_B,
        #     "power_factor": power_factor_B,
        #     "voltage_thd": voltage_thd_B,
        #     "current_thd": current_thd_B,
        #     "timestamp": timestamp_B,
        #     "energy": energy_B
        # }

        # # For Phase C
        # power_watt_C = ade9000.read_active_power_regs()["ActivePowerReg_C"]
        # power_var_C = ade9000.read_reactive_power_regs()["ReactivePowerReg_C"]
        # power_va_C = ade9000.read_apparent_power_regs()["ApparentPowerReg_C"]
        # voltage_rms_C = ade9000.read_voltage_rms_regs()["VoltageRMSReg_C"]
        # current_rms_C = ade9000.read_current_rms_regs()["CurrentRMSReg_C"]
        # power_factor_C = ade9000.read_power_factor_regs_values()["PowerFactorValue_C"]
        # voltage_thd_C = ade9000.read_voltage_thd_regs_values()["VoltageTHDValue_C"]
        # current_thd_C = ade9000.read_current_thd_regs_values()["CurrentTHDValue_C"]
        # timestamp_C = int(time.time())
        # energy_C = power_watt_C/(3.6*10**6) # Placeholder

        # power_data_dict_C = {
        #     "device_id": device_id,
        #     "phase": "C",
        #     "power_watt": power_watt_C,
        #     "power_var": power_var_C,
        #     "power_va": power_va_C,
        #     "voltage_rms": voltage_rms_C,
        #     "current_rms": current_rms_C,
        #     "power_factor": power_factor_C,
        #     "voltage_thd": voltage_thd_C,
        #     "current_thd": current_thd_C,
        #     "timestamp": timestamp_C,
        #     "energy": energy_C
        # }
        # ade9000.close()

        # power_watt = [power_data_dict_A, power_data_dict_B, power_data_dict_C]
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1bmFtZSI6InRlc3QiLCJkZXZpY2VfaWQiOiJyYW5kb20xMiIsImV4cCI6MTc0MjUwOTgyN30.iXXGtAa8egvjlhHI9WSyVCUfh8s9_ucmUsWoH5DrLPw"
        # print("[INFO]: Data Calculated: ", power_watt)


        # energy = energy_A + energy_B + energy_C

        url = BASE_URL+ "/write-data" 
        send_write_data_request(url, dummy_power_data, token)
        cond = False




def send_write_data_request(url,  power_data=None, token=None):
    """
    Sends a POST request to the /write-data endpoint.

    Args:
        url (str): The full URL of the /write-data endpoint.
        token (str): Authorization token.
        power_data (list[dict], optional): List of power data dictionaries.
        energy_data (list[dict], optional): List of energy data dictionaries.

    Raises:
        Exception: If the response status code is not 200.

    Returns:
        dict: JSON response from the server.
    """
    headers= None
    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    
    # data = {
    #     "power_data": power_data or [],
    # }

    try:
        response = requests.post(url, json=power_data, headers=headers)
        if response.status_code != 201:
            print(f"[ERROR]: Failed to send data to server")
            create_local_db()
            save_to_local_db(power_data)
            print("[INFO]: Data saved locally due to network error.")
            raise Exception(f"Request failed with status {response.status_code}: {response.text}")


        print("[INFO]: Message from server: ",response.json())
        return response.json()
    except Exception as e:
        print("[ERROR]: ", str(e))



    

if __name__ == "__main__":
    # setup()
    # loop()
    data_to_server()
    fetch_local_data()
