# Configuration

Library-wide settings via environment variables or programmatic configuration.

## PyGAEBSettings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `default_model` | `PYGAEB_DEFAULT_MODEL` | `anthropic/claude-sonnet-4-6` | LLM model for classification and extraction |
| `classifier_concurrency` | `PYGAEB_CLASSIFIER_CONCURRENCY` | `5` | Max parallel LLM calls |
| `xsd_dir` | `PYGAEB_XSD_DIR` | `None` | Directory containing XSD schemas for validation |
| `log_level` | `PYGAEB_LOG_LEVEL` | `WARNING` | Logging level applied to all `pygaeb.*` loggers |
| `large_file_threshold_mb` | `PYGAEB_LARGE_FILE_THRESHOLD_MB` | `50` | Files above this size trigger large-file optimisations |
| `large_file_item_threshold` | `PYGAEB_LARGE_FILE_ITEM_THRESHOLD` | `10000` | Item count above which large-file heuristics apply |
| `max_file_size_mb` | `PYGAEB_MAX_FILE_SIZE_MB` | `100` | Hard limit on input file size (0 = disabled) |

::: pygaeb.config.PyGAEBSettings
    options:
      show_root_heading: true
      members_order: source

## configure

::: pygaeb.config.configure
    options:
      show_root_heading: true

## get_settings

::: pygaeb.config.get_settings
    options:
      show_root_heading: true

## reset_settings

::: pygaeb.config.reset_settings
    options:
      show_root_heading: true
