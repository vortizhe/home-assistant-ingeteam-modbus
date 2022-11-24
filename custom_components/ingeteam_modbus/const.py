DOMAIN = "ingeteam_modbus"
DEFAULT_NAME = "ingeteam"
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDRESS = 1
DEFAULT_READ_METER = False
DEFAULT_READ_BATTERY = False
CONF_INGETEAM_HUB = "ingeteam_hub"
ATTR_STATUS_DESCRIPTION = "status_description"
ATTR_MANUFACTURER = "Ingeteam"
CONF_MODBUS_ADDRESS = "modbus_address"
CONF_READ_METER = "read_meter"
CONF_READ_BATTERY = "read_battery"

INVERTER_STATUS_TYPES = {
    "Stop_Event": ["Stop event code", "stop_code", None, None],
    "Alarms": ["Alarm code", "alarm_code", None, None],
    # "Code_1": ["Code 1", "alarm_code_1", None, None],
    # "Code_2": ["Code 2", "alarm_code_2", None, None],
    # "Code_3": ["Code 3", "alarm_code_3", None, None],
    "Status": ["Status", "status", None, None],
    "Waiting_Time": ["Waiting Time to Connect to Grid", "waiting_time", "s", None],
}

INVERTER_SENSOR_TYPES = {
    "Active_Power": ["Active Power", "active_power", "W", None],
    "Active_Energy": ["Active Energy", "active_energy", "Wh", None, "active_power"],
    "Reactive_Power": ["Reactive Power", "reactive_power", "W", None],
    "Power_factor": ["Power factor Cosφ", "power_factor", None, None],
    "Active_Power_Reduction_Ratio": ["Active Power Reduction Ratio", "ap_reduction_ratio", "%", None],
    "Active_Power_Reduction_Reason": ["Active Power Reduction Reason", "ap_reduction_reason", None, None],
    "Reactive_Power_Set-Point_Type": ["Reactive Power Set-Point Type", "reactive_setpoint_type", None, None],
    "CL_Voltage": ["Critical Loads. Voltage", "cl_voltage", "V", None],
    "CL_Current": ["Critical Loads. Current", "cl_current", "A", "mdi:current-ac"],
    "CL_Freq": ["Critical Loads. Frequency", "cl_freq", "Hz", None],
    "CL_Active_Power": ["Critical Loads. Active Power", "cl_active_power", "A", None],
    "CL_Reactive_Power": ["Critical Loads. Reactive Power", "cl_reactive_power", "Var", None],
    "IM_Voltage": ["Internal Meter Voltage", "im_voltage", "V", None],
    "IM_Current": ["Internal Meter Current", "im_current", "A", "mdi:current-ac"],
    "IM_Freq": ["Internal Meter Frequency", "im_freq", "Hz", None],
    "IM_Active_Power": ["Internal Active Power", "im_active_power", "W", None],
    "IM_Active_Energy": ["Internal Active Energy", "im_active_energy", "Wh", None, "internal_active_power"],
    "IM_Reactive_Power": ["Internal Reactive Power", "im_reactive_power", "Var", None],
    "IM_Power_Factor": ["Internal Power Factor Cosφ", "im_power_factor", None, None],
    "DC_Bus_Voltaje": ["DC Bus Voltage", "dc_bus_voltage", None, None],
    "Internal_Temperature": ["Internal Temperature", "internal_temp", "°C", None],
    "RMS_Differential_Current": ["RMS Differential Current", "rms_diff_current", "mA", "mdi:current-ac"],
    "DO_1_Status": ["Digital Output 1. Status", "do_1_status", None, None],
    "DO_2_Status": ["Digital Output 2. Status", "do_2_status", None, None],
    "DI_DRM0_Status": ["Digital Input DRM0 Status", "di_drm_status", None, None],
    "DI_2_Status": ["Digital Input 2. Status", "di_2_status", None, None],
    "DI_3_Status": ["Digital Input 3. Status", "di_3_status", None, None],
}

METER_SENSOR_TYPES = {
    "EM_Voltage": ["External Meter AC Voltage", "em_voltage", "V", "mdi:sine-wave"],
    "EM_Frequency": ["External Meter AC Frequency", "em_freq", "Hz", None],
    "EM_Active_Power": ["External Meter AC Active Power", "em_active_power", "W", None],
    "EM_Active_Energy": ["External Meter AC Active Energy", "em_active_energy", "Wh", None, "external_meter_ac_active_power"],
    "EM_Reactive_Power": ["External Meter AC Reactive Power", "em_reactive_power", "Var", None],
}

PV_FIELD_SENSOR_TYPES = {
    "PV1_Voltage": ["PV1 Voltage", "pv1_voltage", "V", None],
    "PV1_Current": ["PV1 Current", "pv1_current", "A", "mdi:current-dc"],
    "PV1_Power": ["PV1 Power", "pv1_power", "W", None],
    "PV1_Energy": ["PV1 Energy", "pv1_energy", "Wh", None, "pv1_power"],
    "PV2_Voltage": ["PV2 Voltage", "pv2_voltage", "V", None],
    "PV2_Current": ["PV2 Current", "pv2_current", "A", "mdi:current-dc"],
    "PV2_Power": ["PV2 Power", "pv2_power", "W", None],
    "PV2_Energy": ["PV2 Energy", "pv2_energy", "Wh", None, "pv1_power"],
}

BATTERY_SENSOR_TYPES = {
    "Battery_Voltage": ["Battery Voltage", "battery_voltage", "V", None],
    "Battery_Current": ["Battery Current", "battery_current", "A",  "mdi:current-dc"],
    "Battery_Power": ["Battery Power", "battery_power", "W", "mdi:battery-charging-100"],
    "Battery_Energy": ["Battery Energy", "battery_energy", "Wh", "mdi:battery-charging-100", "battery_power"],
    "Battery_SOC": ["Battery State of Charge", "battery_state_of_charge", "%", "mdi:battery-high"],
    "Battery_SOH": ["Battery State of Health", "battery_state_of_health", "%", None],
    "Battery_Charging_Voltage": ["Battery Charging Voltage", "battery_charging_voltage", "V", None],
    "Battery_Discharging_Voltage": ["Battery Discharging Voltage", "battery_discharging_voltage", "V", None],
    "Battery_Charging_Current_max": ["Battery Max. Charging Current", "battery_charging_current_max", "A", "mdi:current-dc"],
    "Battery_Discharging_Current_max": ["Battery Max. Discharging Current", "battery_discharging_current_max", "A", "mdi:current-dc"],
    "Battery_Status": ["Battery Status", "battery_status", None, None],
    "Battery_Temp": ["Battery Temp", "battery_temp", "°C", None],
    "Battery_BMS_Alarm": ["Battery BMS Alarm", "battery_bms_alarm", None, None],
    "Battery_Discharch_Limitation": ["Battery Discharge Limitation Reason", "battery_discharge_limitation_reason", None, None],
    "Battery_Voltage_Internal": ["Battery Voltage Internal Sensor", "battery_voltage_internal", "V", None],
}

BOOLEAN_STATUS = {
    0: "Off",
    1: "On"
}

INVERTER_STATUS = {
    0: "Inverter Stopped",
    1: "Starting",
    2: "Off-grid",
    3: "On-grid",
    4: "On-grid (Standby Battery)",
    5: "Waiting to connect to Grid",
    6: "Critical Loads Bypassed to Grid",
    7: "Emergency Charge from PV",
    8: "Emergency Charge from Grid",
    9: "Inverter Locked waiting for Reset",
    10: "Error Mode"
}

BATTERY_STATUS = {
    0: "Standby",
    1: "Discharging",
    2: "Constant Current Charging",
    3: "Constant Voltage Charging",
    4: "Floating",
    5: "Equalizing",
    6: "Error Communication with BMS",
    7: "No Configured",
    8: "Capacity Calibration (Step 1)",
    9: "Capacity Calibration (Step 2)",
    10: "Standby Manual"
}

BATTERY_BMS_ALARMS = {
    0: "High Current Charge",
    1: "High Voltage",
    2: "Low Voltage",
    3: "High Temperatura",
    4: "Low Temperatura",
    5: "BMS Internal",
    6: "Cell Imbalance",
    7: "High Current Discharge",
    8: "System BMS Error",
}

BATTERY_LIMITATION_REASONS = {
    0: "No limitation",
    1: "Heat Sink Temperature",
    2: "PT100 Temperature",
    3: "Low Bus Voltage Protection",
    4: "Battery Settings",
    5: "BMS Communication",
    6: "SOC Max Configured",
    7: "SOC Min Configured",
    8: "Maximum Battery Power",
    9: "Modbus command",
    10: "Digital Input 2",
    11: "Digital Input 3",
    12: "PV Charging scheduling",
}

AP_REDUCTION_REASONS = {
    0: "No limitation",
    1: "Communication",
    2: "PCB Temperature",
    3: "Heat Sink Temperature",
    4: "Pac vs Fac Algorithm",
    5: "Soft Start",
    6: "Charge Power Configured",
    7: "PV Surplus injected to the Loads",
    8: "Pac vs Vac Algorithm",
    9: "Battery Power Limited",
    10: "AC Grid Power Limited",
    11: "Self-Consumption Mode",
    12: "High Bus Voltage Protection",
    13: "LVRT or HVRT Process",
    14: "Nominal AC Current",
    15: "Grid Consumption Protection",
    16: "PV Surplus Injected to the Grid",
}
