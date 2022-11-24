[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

# home-assistant-ingeteam-modbus
Home assistant Custom Component for reading data from Ingeteam inverter through modbus TCP.
Implements Inverter registers from Ingeteam docs [Input registers][1] and [Alarm interpretation and Troubleshooting guide][2]

# Installation
Copy contents of custom_components folder to your home-assistant config/custom_components folder or install through HACS.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Enabling Modbus TCP on Ingeteam Inverter
Modbus is actived by default, just in case:

1. Open up a browser and connect to the inverter local dashboard with installer account, you can find user/pass on right side of the inverter chassis.
2. Go to top menu `Comms` then click `Firewall` on left sidebar menu.
3. Check if Modbus TCP option is enabled on any interface and/or network.

[1]: http://www.ingeras.es/manual/ABH2010IMB08.pdf
[2]: http://www.ingeras.es/manual/ABH2010IMC14.pdf
