# Timeout Calculation in NetWordPingPong

The player's timeout in NetWordPingPong is dynamically calculated at the end of each turn. This document explains the factors that influence the timeout calculation, making the game more strategic and engaging.

## Base Timeout

Each turn starts with a base timeout of **15,000 milliseconds (15 seconds)**. This value is then adjusted based on the player's performance and any active bonuses or penalties.

## Multipliers

The following factors can modify the base timeout:

*   **Speed Multiplier:** A player's response time directly impacts the timeout. The faster a player responds, the greater the speed multiplier. The multiplier is calculated as `1.0 + (1 - response_time_ms / base_timeout)`.

*   **Vowel Multiplier:** Playing a vowel can reduce the opponent's next timeout by a percentage based on the vowel's power. The multiplier is calculated as `1.0 - (0.25 * vowel_power)`.

*   **Cursed Multiplier:** If a player plays a "cursed" letter, their timeout is multiplied by `0.25`.

*   **Pad Combo Multiplier:** If a player is under the effect of an "Attack" combo, their timeout is multiplied by `0.5`.

## Final Timeout

The final timeout is the base timeout multiplied by all applicable multipliers. The final value is capped between a minimum of **3,000 milliseconds (3 seconds)** and a maximum of **60,000 milliseconds (60 seconds)**.

This dynamic timeout calculation adds a layer of strategy to the game, as players must balance speed, vowel usage, and combo attacks to gain an advantage over their opponents.
