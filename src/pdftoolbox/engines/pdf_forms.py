"""Fill interactive PDF forms (AcroForm) with pypdf (BSD-3-Clause).

The engine only reads and updates fields that ALREADY exist in a document. It
never invents a form, never flattens one, and never touches fields the user
did not fill in - the output is a copy of the source with the field values
changed.

Design rules shared with the rest of the app:
  * the original file is never overwritten (:func:`pdf_edit.unique_path`),
  * every failure is reported as a :class:`ConversionError`,
  * only permissive dependencies are used, so the clean build stays AGPL-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from . import ConversionError
from .pdf_edit import unique_path

#: The field types a form can hold, mapped to the wording the GUI shows.
TEXT_FIELD = "text"
CHOICE_FIELD = "choice"
BUTTON_FIELD = "checkbox"
RADIO_FIELD = "radio"

#: A button that is switched off always carries this state name.
OFF_STATE = "/Off"


@dataclass
class FormField:
    """One interactive field of a document."""

    #: The qualified field name, e.g. "applicant.first_name".
    name: str
    #: The field type: text, choice, checkbox or radio.
    kind: str
    #: The tooltip the document gives the field, or its name when it has none.
    label: str
    #: The current value: text for text/choice fields, True/False for buttons.
    value: str | bool = ""
    #: The choices of a choice field.
    options: list[str] = field(default_factory=list)
    #: The 1-based page the field sits on.
    page: int = 1
    #: The state names a checkbox or radio button can take, e.g. "/Off", "/Yes".
    states: list[str] = field(default_factory=list)

    @property
    def is_button(self) -> bool:
        return self.kind in (BUTTON_FIELD, RADIO_FIELD)

    @property
    def on_state(self) -> str:
        """The state name that switches a button on.

        NOTE: producers choose their own names ("/Yes", "/1", "/On"), so the
        first state that is not "/Off" is the one to use.
        """
        for state in self.states:
            if state != OFF_STATE:
                return state
        return "/Yes"


def _open_reader(src: Path) -> PdfReader:
    """Read ``src``, trying the empty password for edit-protected files."""
    try:
        reader = PdfReader(str(src))
    except (PdfReadError, OSError) as exc:
        raise ConversionError(f"cannot read {Path(src).name}: {exc}") from exc
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ConversionError(
                    f"{Path(src).name} is password-protected; unlock it first"
                )
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConversionError(
                f"{Path(src).name} is password-protected; unlock it first"
            ) from exc
    return reader


def _page_of_field(reader: PdfReader, name: str) -> int:
    """The 1-based page a field sits on, or 1 when it cannot be located."""
    for index, page in enumerate(reader.pages, start=1):
        for annot in page.get("/Annots") or []:
            try:
                obj = annot.get_object()
            except Exception:  # noqa: BLE001 - a broken widget must not stop the scan
                continue
            if str(obj.get("/T") or "") == name:
                return index
    return 1



def list_fields(src: Path) -> list[FormField]:
    """Every interactive field of ``src``, in document order.

    NOTE: a document without a form yields an empty list rather than an
    error, so the GUI can say "this PDF has no fillable fields".
    """
    reader = _open_reader(Path(src))
    try:
        raw = reader.get_fields()
    except Exception as exc:  # noqa: BLE001 - a malformed form must not crash
        raise ConversionError(f"cannot read the form fields: {exc}") from exc
    if not raw:
        return []

    fields: list[FormField] = []
    for name, entry in raw.items():
        try:
            field_obj = entry.get_object()
        except Exception:  # noqa: BLE001
            continue
        kind = str(field_obj.get("/FT") or "")
        label = str(field_obj.get("/TU") or name)
        states = [str(state) for state in (field_obj.get("/_States_") or [])]

        if kind == "/Tx":
            kind_name = TEXT_FIELD
            value: str | bool = str(field_obj.get("/V") or "")
            options: list[str] = []
        elif kind == "/Ch":
            kind_name = CHOICE_FIELD
            value = str(field_obj.get("/V") or "")
            options = [str(option) for option in (field_obj.get("/Opt") or [])]
        elif kind == "/Btn":
            # a radio button carries the radio flag in its field flags
            flags = int(field_obj.get("/Ff") or 0)
            kind_name = RADIO_FIELD if flags & (1 << 15) else BUTTON_FIELD
            value = str(field_obj.get("/V") or "") != OFF_STATE
            options = []
        else:
            # push buttons and anything unknown carry no value to fill
            continue

        fields.append(
            FormField(
                name=name,
                kind=kind_name,
                label=label,
                value=value,
                options=options,
                page=_page_of_field(reader, name),
                states=states,
            )
        )
    return fields



def fill_fields(
    src: Path,
    out_path: Path,
    values: dict[str, str | bool],
) -> Path:
    """Write a copy of ``src`` with the named fields filled in.

    ``values`` maps a field name to a text, a choice, or True/False for a
    checkbox or radio button. Fields that are not listed keep the value they
    already had.
    """
    if not values:
        raise ConversionError("no field values were given")

    reader = _open_reader(Path(src))
    try:
        raw = reader.get_fields()
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"cannot read the form fields: {exc}") from exc
    if not raw:
        raise ConversionError("this PDF carries no fillable form fields")

    known = {name: entry for name, entry in raw.items()}
    wanted: dict[str, str] = {}
    for name, value in values.items():
        entry = known.get(name)
        if entry is None:
            raise ConversionError(f"this PDF has no field called '{name}'")
        field_obj = entry.get_object()
        kind = str(field_obj.get("/FT") or "")
        if kind == "/Btn":
            states = [str(state) for state in (field_obj.get("/_States_") or [])]
            on_state = "/Yes"
            for state in states:
                if state != OFF_STATE:
                    on_state = state
                    break
            # NOTE: a button stores a state NAME, not a boolean, so the value
            # must be turned into the producer's own "on" name
            wanted[name] = on_state if value else OFF_STATE
        elif kind == "/Ch":
            options = [str(option) for option in (field_obj.get("/Opt") or [])]
            text = str(value)
            if options and text not in options:
                raise ConversionError(
                    f"'{text}' is not one of the choices for '{name}'"
                )
            wanted[name] = text
        else:
            wanted[name] = str(value)

    writer = PdfWriter(clone_from=reader)
    try:
        # NOTE: auto_regenerate sets the form's NeedAppearances flag, so a
        # viewer draws the new value instead of showing the old cached one
        writer.update_page_form_field_values(None, wanted)
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"cannot write the form values: {exc}") from exc

    target = unique_path(Path(out_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            writer.write(handle)
    except OSError as exc:
        raise ConversionError(f"cannot write {target.name}: {exc}") from exc
    return target


def field_values(src: Path) -> dict[str, str | bool]:
    """The current value of every field, keyed by field name."""
    return {item.name: item.value for item in list_fields(src)}
