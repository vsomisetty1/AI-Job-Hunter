"""What the form engine knows about a form field (plain data, no browser).

A `FormField` is built from what the page says about a control (labels, ARIA,
legends, nearby text, placeholders), never from a hard-coded selector: the
DOM extraction script tags each control with a `data-ajh` handle at run time,
and the filler addresses controls only through that handle.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

FieldKind = Literal[
    "text", "email", "tel", "url", "number", "date", "textarea", "select", "combobox",
    "radio", "checkbox", "checkbox_group", "yes_no", "file",
]  # fmt: skip
TEXT_KINDS = frozenset({"text", "email", "tel", "url", "number", "date", "textarea"})
CHOICE_KINDS = frozenset({"select", "combobox", "radio", "checkbox_group", "yes_no"})
HANDLE_ATTR = "data-ajh"
# Labels that name the control's button, not the question ("Attach", "Upload").
GENERIC_LABELS = re.compile(
    r"^(attach|upload|choose( a)? file|browse|select( a)? file|drop( files)?( here)?|"
    r"enter manually|type here|select|select\.\.\.|start typing\.\.\.|none)$",
    re.IGNORECASE,
)
_REQUIRED_MARK = re.compile(r"\s*[*✱∗]+\s*$|\s*\(required\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class FieldOption:
    label: str
    value: str = ""
    handle: str = ""  # the option's own handle (radio/checkbox/button options)


@dataclass(frozen=True)
class FormField:
    key: str  # stable across reloads: name, id, or the label
    handle: str  # data-ajh value of the control (a group: its first member)
    kind: FieldKind
    label: str
    hints: tuple[str, ...] = ()  # every other text describing it (ARIA, placeholder, name)
    required: bool = False
    options: tuple[FieldOption, ...] = ()
    multiple: bool = False
    accept: str | None = None
    autocomplete: str | None = None
    value: str = ""  # what the control shows now
    filled: bool = False
    invalid: bool = False
    error: str | None = None
    visible: bool = True

    @property
    def text(self) -> str:
        """Everything that describes the field, for matching."""
        return " ".join([self.label, *self.hints])

    @classmethod
    def from_dom(cls, raw: dict[str, Any]) -> FormField:
        labels = [clean_label(str(t)) for t in raw.get("labels", []) if str(t).strip()]
        specific = [t for t in labels if t and not GENERIC_LABELS.match(t)]
        label = specific[0] if specific else (labels[0] if labels else "")
        hints = tuple(dict.fromkeys(t for t in labels + list(raw.get("hints", [])) if t))
        kind = raw.get("kind", "text")
        return cls(
            key=str(raw.get("key") or label or raw.get("handle", "")),
            handle=str(raw.get("handle", "")),
            kind=kind if kind in _KINDS else "text",
            label=label,
            hints=tuple(h for h in hints if h != label),
            required=bool(raw.get("required"))
            or any(marks_required(str(t)) for t in raw.get("labels", [])[:2]),
            options=tuple(
                FieldOption(
                    clean_label(str(o.get("label", ""))),
                    str(o.get("value", "")),
                    str(o.get("handle", "")),
                )  # fmt: skip
                for o in raw.get("options", [])
                if str(o.get("label", "")).strip()
            ),
            multiple=bool(raw.get("multiple")),
            accept=raw.get("accept") or None,
            autocomplete=(raw.get("autocomplete") or None),
            value=str(raw.get("value") or ""),
            filled=bool(raw.get("filled")),
            invalid=bool(raw.get("invalid")),
            error=(str(raw["error"]).strip() or None) if raw.get("error") else None,
            visible=bool(raw.get("visible", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "required": self.required,
            "options": [o.label for o in self.options][:50],
            "value": self.value,
            "filled": self.filled,
            "invalid": self.invalid,
            "error": self.error,
        }


_KINDS = frozenset(FieldKind.__args__)  # type: ignore[attr-defined]


_INNER_MARK = re.compile(r"\s[*\u2731\u2217]\s")


def clean_label(text: str) -> str:
    """Collapse whitespace and drop required markers ("Email*", "Name ✱").

    A wrapping <label> can hold more than the question ("Resume/CV ✱ ATTACH
    RESUME/CV Couldn't auto-read resume"): the question ends at the marker."""
    text = " ".join(text.split())
    text = _INNER_MARK.split(text, maxsplit=1)[0]
    return _REQUIRED_MARK.sub("", text).strip()


def marks_required(text: str) -> bool:
    text = " ".join(text.split())
    return bool(_REQUIRED_MARK.search(text) or _INNER_MARK.search(text))


def normalize(text: str) -> str:
    """Lowercase words only, for pattern matching."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower().replace("e-mail", "email")))


@dataclass
class FieldOutcome:
    """What happened to one field during a run (stored in the checkpoint)."""

    key: str
    label: str
    kind: str
    required: bool
    status: Literal["filled", "uploaded", "needs_you", "consent", "skipped", "failed"]
    value: str = ""  # shown to the user: the text typed or the option chosen
    source: str = ""  # profile, resume, settings, package_answer, user, rule
    reason: str = ""  # why it was not filled, or how it was chosen
    sensitive: bool = False  # voluntary self-identification (EEO)
    options: list[str] = field(default_factory=list)  # for answering in review
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "status": self.status,
            "value": self.value,
            "source": self.source,
            "reason": self.reason,
            "sensitive": self.sensitive,
            "options": self.options,
        }
