import time

# Real spidev on the Pi, the virtual meter board elsewhere (see hal/__init__.py).
# (The unused smbus2 import was dropped: it only imports on Linux.)
from hal import spi as spidev
from ADE9000API_header import *
from ADE9000CalibrationInputs import *
from ADE9000RegMap import *

class ADE9000:
    def __init__(self):
        self._chipSelect_Pin = None



    def spi_init(self, spi_bus=0, spi_device=0, spi_speed=1000000, chip_select_pin=8):
        self._chipSelect_Pin = chip_select_pin
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)  # Open SPI bus
        self.spi.max_speed_hz = spi_speed  # Set SPI speed
        self.spi.mode = 0  # SPI Mode 0

    def spi_write_16(self, address, data):
        temp_address = (address << 4) & 0xFFF0
        tx_data = [temp_address >> 8, temp_address & 0xFF, data >> 8, data & 0xFF]
        self.spi.xfer2(tx_data)

    def spi_write_32(self, address, data):
        temp_address = (address << 4) & 0xFFF0
        high_packet = (data >> 16) & 0xFFFF
        low_packet = data & 0xFFFF
        tx_data = [
            temp_address >> 8, temp_address & 0xFF,
            high_packet >> 8, high_packet & 0xFF,
            low_packet >> 8, low_packet & 0xFF
        ]
        self.spi.xfer2(tx_data)

    def spi_read_16(self, address):
        temp_address = ((address << 4) & 0xFFF0) + 8
        tx_data = [temp_address >> 8, temp_address & 0xFF, 0x00, 0x00]
        rx_data = self.spi.xfer2(tx_data)
        return (rx_data[2] << 8) | rx_data[3]

    def spi_read_32(self, address):
        temp_address = ((address << 4) & 0xFFF0) + 8
        tx_data = [temp_address >> 8, temp_address & 0xFF, 0x00, 0x00, 0x00, 0x00]
        rx_data = self.spi.xfer2(tx_data)
        return (rx_data[2] << 24) | (rx_data[3] << 16) | (rx_data[4] << 8) | rx_data[5]

    def setup_ADE9000(self):
        # Assuming constants are defined elsewhere
        self.spi_write_16(ADDR_PGA_GAIN, ADE9000_PGA_GAIN)
        self.spi_write_32(ADDR_CONFIG0, ADE9000_CONFIG0)
        self.spi_write_16(ADDR_CONFIG1, ADE9000_CONFIG1)
        self.spi_write_16(ADDR_CONFIG2, ADE9000_CONFIG2)
        self.spi_write_16(ADDR_CONFIG3, ADE9000_CONFIG3)
        self.spi_write_16(ADDR_ACCMODE, ADE9000_ACCMODE)
        self.spi_write_16(ADDR_TEMP_CFG, ADE9000_TEMP_CFG)
        self.spi_write_16(ADDR_ZX_LP_SEL, ADE9000_ZX_LP_SEL)
        self.spi_write_32(ADDR_MASK0, ADE9000_MASK0)
        self.spi_write_32(ADDR_MASK1, ADE9000_MASK1)
        self.spi_write_32(ADDR_EVENT_MASK, ADE9000_EVENT_MASK)
        self.spi_write_16(ADDR_WFB_CFG, ADE9000_WFB_CFG)
        self.spi_write_32(ADDR_VLEVEL, ADE9000_VLEVEL)
        self.spi_write_32(ADDR_DICOEFF, ADE9000_DICOEFF)
        self.spi_write_16(ADDR_EGY_TIME, ADE9000_EGY_TIME)
        self.spi_write_16(ADDR_EP_CFG, ADE9000_EP_CFG)
        self.spi_write_16(ADDR_RUN, ADE9000_RUN_ON)

    def close(self):
        self.spi.close()


    def spi_burst_read_resampled_wfb(self, address, read_element_length):
        """Performs a burst read of resampled waveform buffer data"""
        temp_address = ((address << 4) & 0xFFF0) + 8
        self.spi.xfer2([temp_address >> 8, temp_address & 0xFF])  # Send the starting address

        resampled_data = {
            "IA_Resampled": [],
            "VA_Resampled": [],
            "IB_Resampled": [],
            "VB_Resampled": [],
            "IC_Resampled": [],
            "VC_Resampled": [],
            "IN_Resampled": []
        }

        for _ in range(read_element_length):
            resampled_data["IA_Resampled"].append(self.spi_transfer16(0))
            resampled_data["VA_Resampled"].append(self.spi_transfer16(0))
            resampled_data["IB_Resampled"].append(self.spi_transfer16(0))
            resampled_data["VB_Resampled"].append(self.spi_transfer16(0))
            resampled_data["IC_Resampled"].append(self.spi_transfer16(0))
            resampled_data["VC_Resampled"].append(self.spi_transfer16(0))
            resampled_data["IN_Resampled"].append(self.spi_transfer16(0))

        return resampled_data



    def read_active_power_regs(self):
        return {
            "ActivePowerReg_A": sign_extend_32(self.spi_read_32(ADDR_AWATT)) * 4.73755*10**(-3),
            "ActivePowerReg_B": sign_extend_32(self.spi_read_32(ADDR_BWATT)) * 4.73755*10**(-3),
            "ActivePowerReg_C": sign_extend_32(self.spi_read_32(ADDR_CWATT)) * 4.73755*10**(-3),
        }

    def read_reactive_power_regs(self):
        """Reads reactive power registers AVAR, BVAR, CVAR"""
        return {
            "ReactivePowerReg_A": sign_extend_for_VAr_32(self.spi_read_32(ADDR_AVAR))*4.73755*10**(-3),
            "ReactivePowerReg_B": sign_extend_for_VAr_32(self.spi_read_32(ADDR_BVAR))*4.73755*10**(-3),
            "ReactivePowerReg_C": sign_extend_for_VAr_32(self.spi_read_32(ADDR_CVAR))*4.73755*10**(-3)
        }

    def read_apparent_power_regs(self):
        """Reads apparent power registers AVA, BVA, CVA"""
        return {
            "ApparentPowerReg_A": self.spi_read_32(ADDR_AVA)*(4.73755*10**(-3)),
            "ApparentPowerReg_B": self.spi_read_32(ADDR_BVA)*(4.73755*10**(-3)),
            "ApparentPowerReg_C": self.spi_read_32(ADDR_CVA)*(4.73755*10**(-3))
        }

    def read_voltage_rms_regs(self):
        """Reads voltage RMS registers AVRMS, BVRMS, CVRMS"""
        return {
            "VoltageRMSReg_A": self.spi_read_32(ADDR_AVRMS)*(10.73364*10**(-6)),
            "VoltageRMSReg_B": self.spi_read_32(ADDR_BVRMS)*(10.73364*10**(-6)),
            "VoltageRMSReg_C": self.spi_read_32(ADDR_CVRMS)*(10.73364*10**(-6))
        }

    def read_current_rms_regs(self):
        """Reads current RMS registers AIRMS, BIRMS, CIRMS, NIRMS"""
        return {
            "CurrentRMSReg_A": self.spi_read_32(ADDR_AIRMS)*3.28849*10**(-6),
            "CurrentRMSReg_B": self.spi_read_32(ADDR_BIRMS)*3.28849*10**(-6),
            "CurrentRMSReg_C": self.spi_read_32(ADDR_CIRMS)*3.28849*10**(-6),
            "CurrentRMSReg_N": self.spi_read_32(ADDR_NIRMS)*3.28849*10**(-6)
        }

    def read_fund_active_power_regs(self):
        """Reads fundamental active power registers AFWATT, BFWATT, CFWATT"""
        return {
            "FundActivePowerReg_A": self.spi_read_32(ADDR_AFWATT),
            "FundActivePowerReg_B": self.spi_read_32(ADDR_BFWATT),
            "FundActivePowerReg_C": self.spi_read_32(ADDR_CFWATT)
        }

    def read_fund_reactive_power_regs(self):
        """Reads fundamental reactive power registers AFVAR, BFVAR, CFVAR"""
        return {
            "FundReactivePowerReg_A": self.spi_read_32(ADDR_AFVAR),
            "FundReactivePowerReg_B": self.spi_read_32(ADDR_BFVAR),
            "FundReactivePowerReg_C": self.spi_read_32(ADDR_CFVAR)
        }

    def read_fund_apparent_power_regs(self):
        """Reads fundamental apparent power registers AFVA, BFVA, CFVA"""
        return {
            "FundApparentPowerReg_A": self.spi_read_32(ADDR_AFVA),
            "FundApparentPowerReg_B": self.spi_read_32(ADDR_BFVA),
            "FundApparentPowerReg_C": self.spi_read_32(ADDR_CFVA)
        }

    def read_fund_voltage_rms_regs(self):
        """Reads fundamental voltage RMS registers AVFRMS, BVFRMS, CVFRMS"""
        return {
            "FundVoltageRMSReg_A": self.spi_read_32(ADDR_AVFRMS),
            "FundVoltageRMSReg_B": self.spi_read_32(ADDR_BVFRMS),
            "FundVoltageRMSReg_C": self.spi_read_32(ADDR_CVFRMS)
        }

    def read_fund_current_rms_regs(self):
        """Reads fundamental current RMS registers AIFRMS, BIFRMS, CIFRMS"""
        return {
            "FundCurrentRMSReg_A": self.spi_read_32(ADDR_AIFRMS),
            "FundCurrentRMSReg_B": self.spi_read_32(ADDR_BIFRMS),
            "FundCurrentRMSReg_C": self.spi_read_32(ADDR_CIFRMS)
        }

    def read_half_voltage_rms_regs(self):
        """Reads half-cycle voltage RMS registers AVRMS_ONE, BVRMS_ONE, CVRMS_ONE"""
        return {
            "HalfVoltageRMSReg_A": self.spi_read_32(ADDR_AVRMSONE),
            "HalfVoltageRMSReg_B": self.spi_read_32(ADDR_BVRMSONE),
            "HalfVoltageRMSReg_C": self.spi_read_32(ADDR_CVRMSONE)
        }

    def read_half_current_rms_regs(self):
        """Reads half-cycle current RMS registers AIRMSONE, BIRMSONE, CIRMSONE, NIRMSONE"""
        return {
            "HalfCurrentRMSReg_A": self.spi_read_32(ADDR_AIRMSONE),
            "HalfCurrentRMSReg_B": self.spi_read_32(ADDR_BIRMSONE),
            "HalfCurrentRMSReg_C": self.spi_read_32(ADDR_CIRMSONE),
            "HalfCurrentRMSReg_N": self.spi_read_32(ADDR_NIRMSONE)
        }

    def read_ten12_voltage_rms_regs(self):
        """Reads 10/12 cycle voltage RMS registers AVRMS1012, BVRMS1012, CVRMS1012"""
        return {
            "Ten12VoltageRMSReg_A": self.spi_read_32(ADDR_AVRMS1012),
            "Ten12VoltageRMSReg_B": self.spi_read_32(ADDR_BVRMS1012),
            "Ten12VoltageRMSReg_C": self.spi_read_32(ADDR_CVRMS1012)
        }

    def read_ten12_current_rms_regs(self):
        """Reads 10/12 cycle current RMS registers AIRMS1012, BIRMS1012, CIRMS1012, NIRMS1012"""
        return {
            "Ten12CurrentRMSReg_A": self.spi_read_32(ADDR_AIRMS1012),
            "Ten12CurrentRMSReg_B": self.spi_read_32(ADDR_BIRMS1012),
            "Ten12CurrentRMSReg_C": self.spi_read_32(ADDR_CIRMS1012),
            "Ten12CurrentRMSReg_N": self.spi_read_32(ADDR_NIRMS1012)
        }
    def read_voltage_thd_regs_values(self):
        """Reads Voltage THD registers and calculates THD percentage"""
        return {
            "VoltageTHDReg_A": (reg_A := self.spi_read_32(ADDR_AVTHD)),
            "VoltageTHDValue_A": reg_A * 100 / 134217728,
            "VoltageTHDReg_B": (reg_B := self.spi_read_32(ADDR_BVTHD)),
            "VoltageTHDValue_B": reg_B * 100 / 134217728,
            "VoltageTHDReg_C": (reg_C := self.spi_read_32(ADDR_CVTHD)),
            "VoltageTHDValue_C": reg_C * 100 / 134217728,
        }

    def read_current_thd_regs_values(self):
        """Reads Current THD registers and calculates THD percentage"""
        return {
            "CurrentTHDReg_A": (reg_A := self.spi_read_32(ADDR_AITHD)),
            "CurrentTHDValue_A": reg_A * 100 / 134217728,
            "CurrentTHDReg_B": (reg_B := self.spi_read_32(ADDR_BITHD)),
            "CurrentTHDValue_B": reg_B * 100 / 134217728,
            "CurrentTHDReg_C": (reg_C := self.spi_read_32(ADDR_CITHD)),
            "CurrentTHDValue_C": reg_C * 100 / 134217728,
        }

    def read_power_factor_regs_values(self):
        """Reads Power Factor registers and calculates PF.

        xPF is signed (2^27 = 1.0, sign follows active power). Without sign extension
        a PF of -0.99 (export) decoded as ~31.
        """
        return {
            "PowerFactorReg_A": (reg_A := self.spi_read_32(ADDR_APF)),
            "PowerFactorValue_A": sign_extend_32(reg_A) / 134217728,
            "PowerFactorReg_B": (reg_B := self.spi_read_32(ADDR_BPF)),
            "PowerFactorValue_B": sign_extend_32(reg_B) / 134217728,
            "PowerFactorReg_C": (reg_C := self.spi_read_32(ADDR_CPF)),
            "PowerFactorValue_C": sign_extend_32(reg_C) / 134217728,
        }

    def read_period_regs_values(self):
        """Reads Period registers and calculates Frequency"""
        return {
            "PeriodReg_A": (reg_A := self.spi_read_32(ADDR_APERIOD)),
            "FrequencyValue_A": (8000 * 65536) / (reg_A + 1),
            "PeriodReg_B": (reg_B := self.spi_read_32(ADDR_BPERIOD)),
            "FrequencyValue_B": (8000 * 65536) / (reg_B + 1),
            "PeriodReg_C": (reg_C := self.spi_read_32(ADDR_CPERIOD)),
            "FrequencyValue_C": (8000 * 65536) / (reg_C + 1),
        }


    def read_angle_regs_values(self):
        accmode = self.spi_read_16(ADDR_ACCMODE)
        # ACCMODE bit 8 (SELFREQ): 1 = 60 Hz system, 0 = 50 Hz. The old test
        # `(accmode & 0x0100) >= 0` was always true, so 50 Hz angles were scaled as 60 Hz.
        mul_constant = 0.02109375 if (accmode & 0x0100) else 0.017578125

        angle_data = {}
        for angle, addr in {
            "VA_VB": ADDR_ANGL_VA_VB,
            "VB_VC": ADDR_ANGL_VB_VC,
            "VA_VC": ADDR_ANGL_VA_VC,
            "VA_IA": ADDR_ANGL_VA_IA,
            "VB_IB": ADDR_ANGL_VB_IB,
            "VC_IC": ADDR_ANGL_VC_IC,
            "IA_IB": ADDR_ANGL_IA_IB,
            "IB_IC": ADDR_ANGL_IB_IC,
            "IA_IC": ADDR_ANGL_IA_IC
        }.items():
            temp_reg = int(self.spi_read_32(addr))
            angle_data[f"AngleReg_{angle}"] = temp_reg
            angle_data[f"AngleValue_{angle}"] = temp_reg * mul_constant

        return angle_data

    def read_temp_reg_value(self):
        self.spi_write_16(ADDR_TEMP_CFG, ADE9000_TEMP_CFG)
        time.sleep(0.002)

        trim = self.spi_read_32(ADDR_TEMP_TRIM)
        gain = trim & 0xFFFF
        offset = (trim >> 16) & 0xFFFF
        temp_reg = self.spi_read_16(ADDR_TEMP_RSLT)
        temp_value = (offset >> 5) - (temp_reg * gain / 65536.0)

        return {"Temperature_Reg": temp_reg, "Temperature": temp_value}

    def read_energy_watthr_reg_value(self):
        """Reads the accumulated active energy (Wh) for all phases.

        CAL_ENERGY_CC is in uWh per xWATTHR_HI code, so energy = signed(HI) * CC.
        The old code shifted HI left by 32 bits for phases B/C (2^32 times too large)
        and did not sign-extend phase A.
        """
        return {
            f"WATTHR_{ph}": sign_extend_32(self.spi_read_32(reg)) * CAL_ENERGY_CC * 10**(-6)
            for ph, reg in (("A", ADDR_AWATTHR_HI), ("B", ADDR_BWATTHR_HI), ("C", ADDR_CWATTHR_HI))
        }


def sign_extend_32(val):
    """Interpret a 32-bit register value as two's-complement signed.

    The old version returned ``-val + 2**32`` - the *magnitude* - so negative active
    power (export, or a CT clamped backwards) was reported as positive consumption.
    """
    return val - (1 << 32) if val & (1 << 31) else val

def sign_extend_for_VAr_32(val):
    return sign_extend_32(val)

def sign_extend_to_64(value):
    """Sign extends a 32-bit signed integer to a 64-bit signed integer."""
    if value & 0x80000000:  # Check if the sign bit (most significant bit) is set
        # If the sign bit is 1, extend with 1's (negative number)
        return value | 0xFFFFFFFF00000000
    else:
        # If the sign bit is 0, extend with 0's (positive number)
        return value & 0xFFFFFFFF


    # Example usage
    if __name__ == "__main__":
        print("MAIN")
