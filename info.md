[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/vortizhe)
## INGETEAM solar inverter for Home Assistant 

Home assistant Custom Component for reading data from Ingeteam inverter through modbus TCP. Implements Inverter registers from https://www.ingeconsuntraining.info/?page_id=25439.

This custom component is experimental version with featured not (yet) present in standard Hass integration and is

### Features

- Installation through Config Flow UI.
- Separate sensor per register
- Registers are read in small blocks, each on its own fixed interval (5 s for power, 60 s for diagnostics, 90 s for lifetime counters), staggered so two reads never reach the inverter at the same time.
- Possible to select other modbus address than the default of 1
- Supports reading inverter data 
- Supports reading external meter data
- Supports reading battery data
- Create cumulative energy values from de instant measurements with Riemann Sum integration.

### Configuration
Go to the integrations page in your configuration and click on new integration -> Ingeteam Modbus

![inverter](https://user-images.githubusercontent.com/777846/224826986-20ac83e1-bbfe-4163-a1d7-60d6f0778f04.png)
![battery](https://user-images.githubusercontent.com/777846/224826994-f1ba6d64-bee5-42a5-ac97-d91afe945a53.png)

![Screenshot 2023-03-13 at 20 57 35](https://user-images.githubusercontent.com/777846/224827579-798e2254-fdb1-43ef-a5d6-37195bf2ce8a.png)

Graphs made with awesome Mini Graph Card from Karl Kihlström https://github.com/kalkih/mini-graph-card
