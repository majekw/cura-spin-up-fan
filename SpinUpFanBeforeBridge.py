# Copyright (c) 2025 Marek Wodzinski
#
# Script for Cura slicer to spin-up part cooling fan before bridge.
#
# Cura can control/enable cooling fan while printing bridges. But more powerful
# fans don't start instantly and often printer is in the middle of printing
# bridge when fan spin up to target speed. Solution for this is to spin-up fan
# before hotend starts printing bridge. With this plugin it's possible to start
# fan earlier by defined time. For simplicity, there is independent setting
# for fan speed - just set it to the same value as in 'Bridge Fan Speed',
# but it can be set to any other value, for example lower to gradualy spin-up,
# or higher to 'kick' fan as fast as possible, but use lower defined speed
# on bridges.
# 

# Implements a sliding time-window to insert fan commands exactly X seconds 
# before a bridge, regardless of layer changes or command complexity.

from ..Script import Script
import math
from collections import deque

class SpinUpFanBeforeBridge(Script):
    def getSettingDataString(self):
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
                    "description": "Time offset to start the fan before the bridge.",
                    "type": "float",
                    "default_value": 1.5,
                    "unit": "s"
                },
                "target_fan_speed":
                {
                    "label": "Bridge Fan Speed %",
                    "description": "Target fan speed to insert (0-100).",
                    "type": "int",
                    "default_value": 100,
                    "unit": "%"
                }
            }
        }"""

    def get_val(self, line, key):
        # Fast non-regex parsing
        if key not in line:
            return None
        try:
            start = line.find(key) + 1
            # Find the end of the number (space or semicolon or end of line)
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
        lead_time = self.getSettingValueByKey("lead_time")
        fan_pwm = int(self.getSettingValueByKey("target_fan_speed") * 2.55)
        fan_cmd = f"M106 S{fan_pwm} ; SpinUpFanBeforeBridge (Lead: {lead_time}s)"

        # State Tracking
        current_x = 0.0
        current_y = 0.0
        current_f = 3000.0  # Default feedrate (mm/min) if none found early
        total_time = 0.0

        # The Sliding Window
        # Stores tuples: (timestamp, layer_index, line_index)
        # timestamp represents the time at the START of that line's execution
        history = deque()
        
        # We collect insertions to apply them after the single pass
        # Tuple: (layer_index, line_index, string_to_insert)
        insertions = []

        # We split data once to make it addressable, but we keep the structure
        # to reconstruct it fast later.
        layers_lines = [layer.split("\n") for layer in data]

        for layer_idx, lines in enumerate(layers_lines):
            for line_idx, line in enumerate(lines):
                
                # 1. Check for Bridge Trigger
                if ";BRIDGE" in line:
                    # We need to insert the fan command at (total_time - lead_time)
                    target_time = total_time - lead_time
                    
                    # Find the insertion point in our history buffer
                    # Since history is sorted by time, we can find the spot efficiently
                    if len(history) > 0:
                        # We want the first entry where timestamp >= target_time
                        # Optimization: Check the ends first
                        if target_time <= history[0][0]:
                            # Request is older than our history (start of print?)
                            insertions.append((history[0][1], history[0][2], fan_cmd))
                        elif target_time >= history[-1][0]:
                            # Request is in the future? (Should be impossible for lead time)
                            insertions.append((layer_idx, line_idx, fan_cmd))
                        else:
                            # Binary search / Linear scan for the closest point
                            # Since deque isn't indexable for bisect, we iterate backwards or convert.
                            # Given lead_time is usually small (1-5s), linear scan from right is fast.
                            found = False
                            for i in range(len(history) - 1, -1, -1):
                                t, l_i, ln_i = history[i]
                                if t <= target_time:
                                    # We found the point just BEFORE our target time.
                                    # So we insert at the *next* instruction (history[i+1])
                                    # or just use this one as close enough.
                                    # Let's insert at the point immediately following this timestamp
                                    if i + 1 < len(history):
                                        ins_l, ins_ln = history[i+1][1], history[i+1][2]
                                        insertions.append((ins_l, ins_ln, fan_cmd))
                                    else:
                                        insertions.append((l_i, ln_i, fan_cmd))
                                    found = True
                                    break
                            
                            if not found:
                                # Fallback to oldest history
                                insertions.append((history[0][1], history[0][2], fan_cmd))

                # 2. Parse Movement & Accumulate Time
                is_move = False
                if "G1" in line or "G0" in line:
                    is_move = True
                    
                    # Store the state BEFORE this move executes (Insertion Point)
                    # We append to history BEFORE updating time, because if we insert here,
                    # it runs before this move.
                    history.append((total_time, layer_idx, line_idx))

                    # Parse Parameters
                    x = self.get_val(line, "X")
                    y = self.get_val(line, "Y")
                    f = self.get_val(line, "F")

                    # Update Feedrate if present (Modal)
                    if f is not None:
                        current_f = f

                    # Calculate Distance
                    dist = 0.0
                    if x is not None and y is not None:
                        dist = math.hypot(x - current_x, y - current_y)
                        current_x = x
                        current_y = y
                    elif x is not None:
                        dist = abs(x - current_x)
                        current_x = x
                    elif y is not None:
                        dist = abs(y - current_y)
                        current_y = y
                    
                    # Calculate Time (Minutes -> Seconds)
                    if dist > 0 and current_f > 0:
                        move_time = (dist / current_f) * 60.0
                        total_time += move_time

                # 3. Manage Window Size (Pruning)
                # We only need history going back slightly further than lead_time.
                # Adding a small safety margin (e.g. 2x lead time or +5 seconds)
                if len(history) > 0:
                    cutoff_time = total_time - (lead_time * 2.0)
                    # Remove old entries from the left
                    while len(history) > 0 and history[0][0] < cutoff_time:
                        history.popleft()

        # 4. Apply Insertions
        # Sort by Layer DESC, then Line DESC to avoid index shifting issues
        insertions.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Apply
        for l_idx, ln_idx, cmd in insertions:
            layers_lines[l_idx].insert(ln_idx, cmd)

        # 5. Reconstruct Data
        for i in range(len(data)):
            data[i] = "\n".join(layers_lines[i])

        return data
