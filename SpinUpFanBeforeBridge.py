# Copyright (C) 2025 Marek Wodzinski
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
#
# Script for Cura slicer to spin up the part-cooling fan before printing bridge.
#
# Cura can enable and control cooling fan when printing bridges, but more powerful
# fans don't start instantly. Often, the printer is already in the middle of printing
# the bridge by the time the fan reaches the target speed.
#
# The solution is to spin up fan before the hotend starts printing the bridge.
# With this script it's possible to start fan earlier by defined amount of time.
#

from ..Script import Script
import math
from collections import deque

class SpinUpFanBeforeBridge(Script):
    """
    Implements a sliding time-window to insert fan commands exactly X seconds
    before a bridge, regardless of layer changes or command complexity.
    """

    def getSettingDataString(self):
        """
        Provides the JSON setting definitions for the script.
        
        :return: A string containing the JSON setting definitions.
        """
        return """{
            "name": "Spin Up Fan Before Bridge",
            "key": "SpinUpFanBeforeBridge",
            "metadata": {},
            "version": 2,
            "settings":
            {
                "lead_time":
                {
                    "label": "Lead Time (seconds)",
                    "description": "How many seconds before the bridge should the fan be turned on? This compensates for the time it takes for the fan to reach full speed.",
                    "type": "float",
                    "default_value": 1.5,
                    "unit": "s"
                },
                "target_fan_speed":
                {
                    "label": "Bridge Fan Speed %",
                    "description": "Set the desired fan speed for the spin-up command (0-100). For consistent cooling, this should match the 'Bridge Fan Speed' setting in Cura.",
                    "type": "int",
                    "default_value": 100,
                    "unit": "%"
                }
            }
        }"""

    def _get_value(self, line, key):
        """
        Fast, non-regex G-code parameter parsing.
        
        :param line: The G-code line to parse.
        :param key: The parameter key (e.g., 'X', 'Y', 'F').
        :return: The floating point value of the parameter, or None if not found.
        """
        if key not in line:
            return None
        try:
            start = line.find(key) + 1
            # Find the end of the number (space, semicolon, or end of line)
            end = start
            l_len = len(line)
            while end < l_len:
                char = line[end]
                if char == ' ' or char == ';':
                    break
                end += 1
            return float(line[start:end])
        except ValueError:
            return None

    def execute(self, data):
        """
        Main execution method that processes the G-code data.

        :param data: A list of strings, where each string is a layer of G-code.
        :return: The modified list of G-code strings.
        """
        lead_time = self.getSettingValueByKey("lead_time")
        target_fan_speed = self.getSettingValueByKey("target_fan_speed")
        
        # Convert fan speed percentage (0-100) to PWM value (0-255)
        fan_pwm = int((target_fan_speed / 100.0) * 255.0)
        fan_cmd = f"M106 S{fan_pwm} ; SpinUpFanBeforeBridge (Lead: {lead_time}s)"

        # --- State Tracking ---
        # Tracks the extruder's current position and state.
        current_x = 0.0
        current_y = 0.0
        current_z = 0.0
        current_f = 3000.0  # Assumed default feedrate (mm/min).
        total_time = 0.0    # Total elapsed print time in seconds.
        is_relative = False # Tracks G90 (absolute) vs G91 (relative) mode.

        # --- The Sliding Window ---
        # A deque that stores recent G-code commands as tuples:
        # (timestamp, layer_index, line_index)
        # 'timestamp' is the total elapsed time at the START of that command.
        history = deque()
        
        # --- Insertions ---
        # A list to collect all commands to be inserted. We apply them in a
        # separate pass to avoid modifying the list while iterating.
        # Tuple format: (layer_index, line_index, string_to_insert)
        insertions = []

        # We split data once to make it addressable, but we keep the structure
        # to reconstruct it fast later.
        layers_lines = [layer.split("\n") for layer in data]

        for layer_idx, lines in enumerate(layers_lines):
            for line_idx, line in enumerate(lines):
                # Check for coordinate system changes (modal)
                if "G90" in line:
                    is_relative = False
                if "G91" in line:
                    is_relative = True

                # 1. Check for Bridge Trigger
                if ";BRIDGE" in line:
                    # Calculate the target time to insert the fan command.
                    target_time = total_time - lead_time
                    
                    # Find the correct insertion point in our history buffer.
                    if len(history) > 0:
                        # Optimization: Check the boundaries first.
                        if target_time <= history[0][0]:
                            # Target time is before our recorded history; insert at the very beginning.
                            insertions.append((history[0][1], history[0][2], fan_cmd))
                        elif target_time >= history[-1][0]:
                            # This case should ideally not happen with a lead time.
                            # It means the insertion point is the current line.
                            insertions.append((layer_idx, line_idx, fan_cmd))
                        else:
                            # Scan backwards from the most recent entry for efficiency,
                            # as the target is likely to be close.
                            found = False
                            for i in range(len(history) - 1, -1, -1):
                                t, hist_layer_idx, hist_line_idx = history[i]
                                if t <= target_time:
                                    # We found the command that executes *just before* our target time.
                                    # We must insert the fan command *after* it.
                                    if i + 1 < len(history):
                                        ins_l, ins_ln = history[i+1][1], history[i+1][2]
                                        insertions.append((ins_l, ins_ln, fan_cmd))
                                    else: # Should not happen if boundary checks are correct
                                        insertions.append((hist_layer_idx, hist_line_idx, fan_cmd))
                                    found = True
                                    break
                            
                            if not found:
                                # Fallback: If no suitable point is found, insert at the oldest history entry.
                                insertions.append((history[0][1], history[0][2], fan_cmd))

                # 2. Parse Movement & Accumulate Time
                if "G1" in line or "G0" in line:
                    # Append current state to history BEFORE calculating this move's time.
                    history.append((total_time, layer_idx, line_idx))

                    # Parse G-code parameters
                    x = self._get_value(line, "X")
                    y = self._get_value(line, "Y")
                    z = self._get_value(line, "Z")
                    f = self._get_value(line, "F")

                    # Feedrate is modal, so update it if present.
                    if f is not None:
                        current_f = f

                    # Calculate distance of the move and update coordinates.
                    dist = 0.0
                    if is_relative:
                        dx = x if x is not None else 0.0
                        dy = y if y is not None else 0.0
                        dz = z if z is not None else 0.0
                        dist = math.hypot(dx, dy, dz)
                        current_x += dx
                        current_y += dy
                        current_z += dz
                    else: # Absolute positioning
                        new_x = x if x is not None else current_x
                        new_y = y if y is not None else current_y
                        new_z = z if z is not None else current_z
                        dist = math.hypot(new_x - current_x, new_y - current_y, new_z - current_z)
                        current_x = new_x
                        current_y = new_y
                        current_z = new_z
                    
                    # Convert move distance to time (seconds) and add to total.
                    if dist > 0 and current_f > 0:
                        move_time = (dist / current_f) * 60.0
                        total_time += move_time

                # 3. Manage History Window Size (Pruning)
                # To save memory, remove history entries that are older than needed.
                # A safety margin (e.g., 2x lead_time) is added.
                if len(history) > 0:
                    cutoff_time = total_time - (lead_time * 2.0)
                    while len(history) > 0 and history[0][0] < cutoff_time:
                        history.popleft()

        # 4. Apply Insertions
        # Sort by Layer DESC, then Line DESC to ensure inserting a command
        # doesn't shift the indices of subsequent insertions.
        insertions.sort(key=lambda x: (x[0], x[1]), reverse=True)

        for l_idx, ln_idx, cmd in insertions:
            layers_lines[l_idx].insert(ln_idx, cmd)

        # 5. Reconstruct Data
        # Join the lines back into layer strings.
        for i in range(len(data)):
            data[i] = "\n".join(layers_lines[i])

        return data

