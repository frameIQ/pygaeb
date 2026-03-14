# Exceptions

All exceptions inherit from `PyGAEBError`.

## Exception Hierarchy

```
PyGAEBError
├── GAEBParseError           # File not found, format unrecognized, XML parsing failure
├── GAEBValidationError      # Raised in strict mode on first ERROR-severity result
└── ClassificationBackendError  # LLM call failure, import error for optional deps
```

## PyGAEBError

::: pygaeb.exceptions.PyGAEBError
    options:
      show_root_heading: true

## GAEBParseError

::: pygaeb.exceptions.GAEBParseError
    options:
      show_root_heading: true

## GAEBValidationError

::: pygaeb.exceptions.GAEBValidationError
    options:
      show_root_heading: true

## ClassificationBackendError

::: pygaeb.exceptions.ClassificationBackendError
    options:
      show_root_heading: true
