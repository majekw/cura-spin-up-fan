# Spin Up Fan Before Bridge

Script for Cura slicer to spin up the part-cooling fan before printing bridge.

Cura can enable and control cooling fan when printing bridges, but more powerful
fans don't start instantly. Often, the printer is already in the middle of printing
the bridge by then time the fan reaches the target speed.

The solution is to spin up fan **before** the hotend starts printing the bridge.
With this script it's possible to start fan earlier by defined amount of time.

For simplicity, there is an independent setting for fan speed - you can set it
to the same value as in 'Bridge Fan Speed', but it can be set to any other value.
For example you may choose a lower value for gradual spin-up, or a higher value
to 'kick' the fan to speed quickly if you don't use a full speed on bridges.

# Instalation and running

Copy script `SpinUpFanBeforeBridge.py` to `scripts` directory, then restart Cura.

In Cura, go to **Extensions -> Post Processing -> Modify G-Code**, then click 'Add a script'
and choose 'Spin Up Fan Before Bridge'.

- Set 'Lead Time' to the number of seconds your fan needs to spin up.
- Set 'Bridge Fan Speed %' to the desired starting fan speed.

Make sure 'Enable Bridge Settings' and 'Bridge Fan Speed' are enabled in Cura's
'Experimental' section.

# Known limitations

- It can be more generic :-)
- Does not support relative moves

# Copyright and License

Copyright (c) 2025 Marek Wodzinski

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
