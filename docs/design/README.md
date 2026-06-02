# Design Index

This folder collects the project design choices. Start with the overview, then use the more specific files when you want implementation details.

## Recommended Reading Order

1. [Development stages](development_stages.md) gives a short history of the design sequence.
2. [System design](system_design.md) explains the main architecture: frame timing, model prompts, player stats, catch/block logic, turnovers, and awake/sleep.
3. [Project structure](project_structure.md) explains what each repository file does.
4. [Observation and action space](observation_action_space.md) lists what agents see and which JSON actions they can return.
5. [Example V2 prompt](example_prompt.md) shows one complete prompt packet for an awake player.
6. [Game rules and configuration](game_rules_and_config.md) lists the current field, roster, stall, throw score, disc speed, and default settings.
7. [Cost and model setup](cost_and_models.md) explains API cost, tested model settings, and stop behavior.
8. [Changing models](model_switching.md) explains what to edit when using another provider or model.

The short public rules guide lives at [../simple_frisbee_rules.md](../simple_frisbee_rules.md).
