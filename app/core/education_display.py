"""Shared display helpers for education programs."""


def program_display_name(program) -> str:
    """Prefer institution name; fall back to course + country."""
    institution = getattr(program, "institution_name", None)
    if institution:
        return institution
    return f"{program.course_category}, {program.country}"
